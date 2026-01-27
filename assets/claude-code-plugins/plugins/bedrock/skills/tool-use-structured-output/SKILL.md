---
name: tool-use-structured-output
description: Use Bedrock tool_use to guarantee structured JSON outputs from Claude models. Eliminates JSON parsing failures by forcing responses through typed tool schemas.
---

This skill demonstrates using Amazon Bedrock's tool_use feature to get highly reliable structured JSON outputs from Claude models. Instead of hoping the model returns valid JSON, define a tool schema that forces the exact structure you need.

## The Problem

Asking Claude to "return JSON" fails 10-30% of the time:
- Markdown code fences around JSON
- Truncated responses mid-object
- Extra text before/after JSON
- Invalid escaping in strings

## The Solution

Define a tool with your exact output schema. Claude will call the tool with arguments that should match the schema structure. While tool use strongly steers the model toward valid structured output, you should still validate the response and have fallback handling for edge cases.

## Implementation Pattern

### 1. Define Tool Schema

```python
tools = [
    {
        "name": "emit_extraction_result",
        "description": "Return the extracted course information",
        "input_schema": {
            "type": "object",
            "required": ["courses", "confidence", "page_number"],
            "properties": {
                "courses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["course_code", "title"],
                        "properties": {
                            "course_code": {
                                "type": "string",
                                "description": "Course identifier (e.g., CS 101)"
                            },
                            "title": {
                                "type": "string",
                                "description": "Course title"
                            },
                            "credits": {
                                "type": "number",
                                "description": "Credit hours"
                            },
                            "description": {
                                "type": "string",
                                "description": "Course description"
                            }
                        }
                    }
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Extraction confidence score"
                },
                "page_number": {
                    "type": "integer",
                    "description": "Source page number"
                }
            }
        }
    }
]
```

### 2. Invoke Bedrock with Tool

```python
import boto3
import json

bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

response = bedrock.invoke_model(
    modelId='anthropic.claude-3-5-sonnet-20241022-v2:0',
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "tools": tools,
        "tool_choice": {"type": "tool", "name": "emit_extraction_result"},  # Force tool use
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64_image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": "Extract all courses from this catalog page."
                    }
                ]
            }
        ]
    })
)
```

### 3. Parse Response

```python
result = json.loads(response['body'].read())

# Find tool use in response
for content_block in result.get('content', []):
    if content_block.get('type') == 'tool_use':
        tool_name = content_block.get('name')
        tool_input = content_block.get('input')

        # tool_input should match your schema structure
        # Always validate before using in production
        courses = tool_input['courses']
        confidence = tool_input['confidence']
        page_number = tool_input['page_number']

        # No JSON parsing needed - it's already a dict!
        break
```

## Advanced Patterns

### Enum Constraints

Force specific values:

```python
"status": {
    "type": "string",
    "enum": ["approved", "rejected", "needs_review"]
}
```

### Numeric Ranges

Constrain numbers:

```python
"accuracy": {
    "type": "number",
    "minimum": 0,
    "maximum": 1
},
"score": {
    "type": "integer",
    "enum": [0, 1, 2, 3, 4, 5]  # Discrete scale
}
```

### Nested Objects

Complex structures:

```python
"evaluation": {
    "type": "object",
    "properties": {
        "field_scores": {
            "type": "object",
            "properties": {
                "course_code": {"type": "number", "enum": [0, 0.5, 1]},
                "title": {"type": "number", "enum": [0, 0.5, 1]},
                "credits": {"type": "number", "enum": [0, 0.5, 1]}
            }
        },
        "overall_accuracy": {"type": "number"},
        "reasoning": {"type": "string"}
    }
}
```

## Lambda Integration

```python
import boto3
import json
import logging
from typing import TypedDict, List, NotRequired

logger = logging.getLogger(__name__)

class Course(TypedDict):
    course_code: str
    title: str
    credits: NotRequired[float | None]
    description: NotRequired[str]

class ExtractionResult(TypedDict):
    courses: List[Course]
    confidence: float
    page_number: int

def extract_courses(image_base64: str) -> ExtractionResult:
    bedrock = boto3.client('bedrock-runtime')

    response = bedrock.invoke_model(
        modelId='anthropic.claude-3-5-sonnet-20241022-v2:0',
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "tools": EXTRACTION_TOOLS,
            "tool_choice": {"type": "tool", "name": "emit_extraction_result"},
            "messages": [...]
        })
    )

    result = json.loads(response['body'].read())

    for block in result.get('content', []):
        if block.get('type') == 'tool_use':
            return block['input']  # Type-safe!

    raise ValueError("No tool use in response")
```

## Error Handling

Tool use can still fail in edge cases. Always validate and handle errors:

```python
import boto3
import json
import logging

logger = logging.getLogger(__name__)

def safe_extract(image_base64: str) -> ExtractionResult | None:
    """Extract courses with proper error handling."""
    bedrock = boto3.client('bedrock-runtime')

    try:
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-5-sonnet-20241022-v2:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "tools": EXTRACTION_TOOLS,
                "tool_choice": {"type": "tool", "name": "emit_extraction_result"},
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_base64}},
                            {"type": "text", "text": "Extract all courses from this catalog page."}
                        ]
                    }
                ]
            })
        )

        result = json.loads(response['body'].read())

        # Check for stop reason
        if result.get('stop_reason') == 'tool_use':
            for block in result.get('content', []):
                if block.get('type') == 'tool_use':
                    return block['input']

        # Model refused to use tool (rare)
        if result.get('stop_reason') == 'end_turn':
            logger.warning("Model ended without tool use")
            return None

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return None

    return None
```

## Cost Considerations

Tool definitions count toward input tokens:
- Simple schema: ~200-500 tokens
- Complex schema: ~1000-2000 tokens

For high-volume workloads, keep schemas minimal.

## Success Rate Comparison

| Method | JSON Parse Success Rate |
|--------|------------------------|
| "Return JSON" prompt | 70-80% |
| JSON mode (if available) | 90-95% |
| **Tool use (forced)** | **99%+** |

Tool use is the most reliable method for structured outputs from Claude on Bedrock. However, always validate the response matches your expected schema before using it in production.
