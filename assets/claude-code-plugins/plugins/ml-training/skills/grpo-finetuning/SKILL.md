---
name: grpo-finetuning
description: Implement GRPO (Group Relative Policy Optimization) fine-tuning for vision-language models on small datasets. Use when SFT underperforms or training data is limited (<1000 examples).
---

This skill guides implementation of GRPO fine-tuning for vision-language models, particularly effective when training data is limited. GRPO uses reinforcement learning with custom reward functions instead of traditional supervised fine-tuning.

## When to Use GRPO vs SFT

| Scenario | Recommended Approach |
|----------|---------------------|
| Large dataset (>5000 examples) | SFT (Supervised Fine-Tuning) |
| Small dataset (<1000 examples) | **GRPO** |
| Clear correctness criteria (JSON, format) | **GRPO** |
| Subjective quality (style, tone) | SFT |
| Need diversity in outputs | **GRPO** |

## Core Concepts

GRPO generates multiple completions per prompt, scores them with reward functions, and optimizes the policy to favor higher-reward outputs:

```
Prompt → Generate N completions → Score each with rewards → Policy gradient update
```

## Implementation Pattern

### 1. Define Reward Functions

Create reward functions that return scores between 0 and 1 (or custom ranges):

```python
import json

def formatting_reward_func(completions, **kwargs):
    """Reward valid JSON structure"""
    rewards = []
    for completion in completions:
        try:
            json.loads(completion)
            rewards.append(1.0)
        except json.JSONDecodeError:
            rewards.append(0.0)
    return rewards

def correctness_reward_func(completions, answers, **kwargs):
    """Reward correct field values"""
    rewards = []
    for completion, answer in zip(completions, answers):
        try:
            pred = json.loads(completion)
            ref = json.loads(answer)
            # Compare fields
            matches = sum(1 for k in ref if pred.get(k) == ref[k])
            rewards.append(matches / len(ref) * 2.0)  # Scale to 0-2
        except:
            rewards.append(0.0)
    return rewards

def anti_hallucination_reward(completions, answers, **kwargs):
    """Penalize extra items not in reference"""
    rewards = []
    for completion, answer in zip(completions, answers):
        try:
            pred_items = len(json.loads(completion))
            ref_items = len(json.loads(answer))
            extra = max(0, pred_items - ref_items)
            rewards.append(-0.5 * extra)  # Penalty for hallucination
        except:
            rewards.append(0.0)
    return rewards
```

### 2. Training Configuration

Key hyperparameters for GRPO (different from SFT):

```python
from trl import GRPOConfig, GRPOTrainer

config = GRPOConfig(
    # GRPO-specific
    num_generations=2,          # Completions per prompt (2-8)

    # Lower learning rate than SFT
    learning_rate=5e-6,         # NOT 2e-4 like SFT

    # Standard training
    per_device_train_batch_size=1,
    gradient_accumulation_steps=4,
    num_train_epochs=1,

    # Generation settings
    max_completion_length=1024,
    max_prompt_length=512,

    # Optimization
    warmup_ratio=0.1,
    logging_steps=1,
    save_steps=50,
)
```

### 3. Dataset Format

GRPO expects prompts and reference answers:

```python
from datasets import Dataset
from PIL import Image

dataset = Dataset.from_dict({
    "prompt": [
        "Extract courses from this image...",
        "List all courses shown...",
    ],
    "image": [
        Image.open("page1.png"),
        Image.open("page2.png"),
    ],
    "answer": [
        '[{"course_code": "CS101", "title": "Intro to CS"}]',
        '[{"course_code": "MATH201", "title": "Calculus II"}]',
    ],
})
```

### 4. Trainer Setup

```python
from unsloth import FastVisionModel

# Load model with 4-bit quantization
model, tokenizer = FastVisionModel.from_pretrained(
    "unsloth/Qwen2-VL-7B-Instruct-bnb-4bit",
    load_in_4bit=True,
)

# Apply LoRA
model = FastVisionModel.get_peft_model(
    model,
    r=16,               # LoRA rank
    lora_alpha=32,      # Usually 2x rank
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj"
    ],
    lora_dropout=0.05,
)

# Initialize trainer
trainer = GRPOTrainer(
    model=model,
    processing_class=tokenizer,
    config=config,
    train_dataset=dataset,
    reward_funcs=[
        formatting_reward_func,
        correctness_reward_func,
        anti_hallucination_reward,
    ],
)

trainer.train()
```

## AWS Infrastructure

### SageMaker Training Job

GRPO requires more VRAM than SFT due to multiple generations:

| Model Size | SFT Instance | GRPO Instance |
|------------|--------------|---------------|
| 7-8B | ml.g5.2xlarge (24GB) | ml.g5.4xlarge (48GB) or ml.p4d.24xlarge |
| 13B | ml.g5.4xlarge | ml.p4d.24xlarge |
| 70B | ml.p4d.24xlarge | ml.p5.48xlarge |

### Docker Container

**Security Note**: The example below uses a mutable third-party image tag. For production use, you should:
1. Pin to a specific version or image digest (e.g., `@sha256:...`)
2. Mirror the image to your own registry (e.g., Amazon ECR)
3. Scan the image for vulnerabilities before use

```dockerfile
# Pin to a specific version for reproducibility and security
# Check https://github.com/unslothai/unsloth/releases for latest stable versions
FROM ghcr.io/unslothai/unsloth:2024.12  # Use specific version, not :stable

# Add AWS dependencies without breaking numpy/scipy
RUN pip install --no-cache-dir --no-deps boto3 botocore

COPY grpo_train.py /opt/ml/code/
ENTRYPOINT ["python3", "/opt/ml/code/grpo_train.py"]
```

For maximum security, mirror the image to your own ECR registry:

```bash
# Pull, scan, and push to ECR
docker pull ghcr.io/unslothai/unsloth:2024.12
docker tag ghcr.io/unslothai/unsloth:2024.12 ${AWS_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/unsloth:2024.12
docker push ${AWS_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/unsloth:2024.12
```

### Training Time Estimation

GRPO is slower than SFT due to generation overhead:

```
Time per step ≈ 150-200 seconds (vs 30-50s for SFT)
Total time ≈ num_examples × time_per_step / batch_size
```

For 1000 examples: ~45-55 hours on ml.p4d.24xlarge

## Common Issues

### 1. OOM During Generation
**Symptom**: Exit code 139 (SIGSEGV)
**Fix**: Reduce `num_generations` or `max_completion_length`, or use larger instance

### 2. Zero Rewards
**Symptom**: `reward_std: 0.0` in logs
**Fix**: Reward functions may be too strict; add partial credit

### 3. No Learning Signal
**Symptom**: `loss: 0.0` throughout training
**Fix**: Ensure reward variance between generations; check `frac_reward_zero_std`

## Success Metrics

Monitor these in CloudWatch/logs:
- `reward/mean`: Should increase over training
- `reward_std`: Non-zero indicates learning signal
- `completions/clipped_ratio`: High ratio suggests max_length too short
- `kl`: Should stay small (policy not diverging too far)
