---
name: async-inference
description: Implement SageMaker async inference with S3-based I/O and polling. Use for long-running inference (>60s), large payloads, or batch processing workloads.
---

This skill guides implementation of SageMaker async inference, ideal for workloads that exceed real-time inference limits (60-second timeout, 6MB payload). Async inference stores inputs/outputs in S3 and supports polling or SNS notifications.

## When to Use Async Inference

| Scenario | Inference Type |
|----------|---------------|
| Response < 60 seconds | Real-time |
| Response 1-15 minutes | **Async** |
| Payload > 6MB | **Async** |
| Batch processing | **Async** or Batch Transform |
| Cost-sensitive (scale to zero) | **Async** with auto-scaling |

## Architecture

```
┌─────────┐    ┌──────────────┐    ┌─────────────────┐
│ Lambda  │───▶│ S3 (input)   │───▶│ SageMaker Async │
└─────────┘    └──────────────┘    │    Endpoint     │
                                   └────────┬────────┘
                                            │
              ┌──────────────┐              │
              │ S3 (output)  │◀─────────────┘
              │   or         │
              │ S3 (failure) │
              └──────┬───────┘
                     │
              ┌──────▼───────┐
              │ Poll / SNS   │
              └──────────────┘
```

## Implementation

### 1. CDK Endpoint Configuration

```typescript
import * as sagemaker from 'aws-cdk-lib/aws-sagemaker';

const asyncConfig = new sagemaker.CfnEndpointConfig(this, 'AsyncConfig', {
  endpointConfigName: 'my-async-endpoint-config',
  productionVariants: [{
    modelName: model.attrModelName,
    variantName: 'AllTraffic',
    instanceType: 'ml.g5.2xlarge',
    initialInstanceCount: 1,
  }],
  asyncInferenceConfig: {
    outputConfig: {
      s3OutputPath: `s3://${bucket.bucketName}/output/`,
      s3FailurePath: `s3://${bucket.bucketName}/failure/`,
      // Optional: SNS notification
      notificationConfig: {
        successTopic: successTopic.topicArn,
        errorTopic: errorTopic.topicArn,
      },
    },
    clientConfig: {
      maxConcurrentInvocationsPerInstance: 4,
    },
  },
});
```

### 2. TypeScript Client Implementation

```typescript
import {
  SageMakerRuntimeClient,
  InvokeEndpointAsyncCommand
} from '@aws-sdk/client-sagemaker-runtime';
import {
  S3Client,
  GetObjectCommand,
  PutObjectCommand,
  ListObjectsV2Command
} from '@aws-sdk/client-s3';
import { v4 as uuid } from 'uuid';

interface AsyncInferenceResult<T> {
  success: boolean;
  data?: T;
  error?: string;
  inferenceId: string;
}

export class SageMakerAsyncClient {
  private sagemaker: SageMakerRuntimeClient;
  private s3: S3Client;
  private bucket: string;
  private endpointName: string;

  constructor(config: { bucket: string; endpointName: string; region: string }) {
    this.sagemaker = new SageMakerRuntimeClient({ region: config.region });
    this.s3 = new S3Client({ region: config.region });
    this.bucket = config.bucket;
    this.endpointName = config.endpointName;
  }

  async invoke<T>(payload: object): Promise<AsyncInferenceResult<T>> {
    const inferenceId = uuid();
    const inputKey = `input/${inferenceId}/request.json`;

    // 1. Upload input to S3
    await this.s3.send(new PutObjectCommand({
      Bucket: this.bucket,
      Key: inputKey,
      Body: JSON.stringify(payload),
      ContentType: 'application/json',
    }));

    // 2. Invoke async endpoint
    const response = await this.sagemaker.send(new InvokeEndpointAsyncCommand({
      EndpointName: this.endpointName,
      InputLocation: `s3://${this.bucket}/${inputKey}`,
      InvocationTimeoutSeconds: 3600,  // 1 hour max
      RequestTTLSeconds: 21600,        // 6 hour TTL
    }));

    // Validate OutputLocation is present
    const outputLocation = response.OutputLocation;
    if (!outputLocation) {
      return {
        success: false,
        error: 'OutputLocation not returned from async invocation',
        inferenceId,
      };
    }

    // 3. Poll for result
    return this.pollForResult<T>(inferenceId, outputLocation);
  }

  private async pollForResult<T>(
    inferenceId: string,
    outputLocation: string,
    maxWaitMs: number = 1200000,  // 20 minutes
    initialPollIntervalMs: number = 5000,
    maxPollIntervalMs: number = 30000
  ): Promise<AsyncInferenceResult<T>> {
    const startTime = Date.now();
    const outputKey = outputLocation.replace(`s3://${this.bucket}/`, '');
    // Extract output filename to construct failure path
    const outputFileName = outputKey.split('/').pop()!;
    const failureKey = `failure/${outputFileName}`;
    let pollIntervalMs = initialPollIntervalMs;

    while (Date.now() - startTime < maxWaitMs) {
      // Check for success
      try {
        const result = await this.s3.send(new GetObjectCommand({
          Bucket: this.bucket,
          Key: outputKey,
        }));

        if (!result.Body) {
          return {
            success: false,
            error: 'Empty response body from S3',
            inferenceId,
          };
        }

        const body = await result.Body.transformToString();

        // Parse JSON with explicit error handling
        let parsed: T;
        try {
          parsed = JSON.parse(body) as T;
        } catch (parseError: any) {
          return {
            success: false,
            error: `Failed to parse inference result JSON: ${parseError?.message ?? 'Unknown parse error'}`,
            inferenceId,
          };
        }

        return {
          success: true,
          data: parsed,
          inferenceId,
        };
      } catch (e: any) {
        // Only continue polling for missing objects
        if (e.name !== 'NoSuchKey' && e?.$metadata?.httpStatusCode !== 404) {
          throw e;
        }
      }

      // Check for failure
      try {
        const failures = await this.listPrefix(failureKey);
        if (failures.length > 0) {
          const errorBody = await this.getObject(failures[0]);
          return {
            success: false,
            error: errorBody,
            inferenceId,
          };
        }
      } catch (e: any) {
        // Treat missing failure objects as "no failure yet", but surface other errors
        if (e?.name !== 'NoSuchKey' && e?.$metadata?.httpStatusCode !== 404) {
          throw e;
        }
      }

      // Exponential backoff for polling interval
      await this.sleep(pollIntervalMs);
      pollIntervalMs = Math.min(pollIntervalMs * 1.5, maxPollIntervalMs);
    }

    return {
      success: false,
      error: 'Timeout waiting for inference result',
      inferenceId,
    };
  }

  // Helper method to list S3 objects with a given prefix
  private async listPrefix(prefix: string): Promise<string[]> {
    const response = await this.s3.send(new ListObjectsV2Command({
      Bucket: this.bucket,
      Prefix: prefix,
    }));
    return (response.Contents ?? []).map(obj => obj.Key!).filter(Boolean);
  }

  // Helper method to get an S3 object's content as a string
  private async getObject(key: string): Promise<string> {
    const response = await this.s3.send(new GetObjectCommand({
      Bucket: this.bucket,
      Key: key,
    }));
    if (!response.Body) {
      throw new Error(`Empty body for S3 object: ${key}`);
    }
    return response.Body.transformToString();
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
```

### 3. Lambda Handler Pattern

```typescript
import { SageMakerAsyncClient } from './sagemaker-client';

interface InferenceRequest {
  imageKey: string;
  prompt: string;
}

// Example response structure - customize based on your model's output
interface InferenceResponse {
  results: Array<{
    id: string;
    content: string;
  }>;
}

export const handler = async (event: InferenceRequest) => {
  const client = new SageMakerAsyncClient({
    bucket: process.env.ASYNC_BUCKET!,
    endpointName: process.env.ENDPOINT_NAME!,
    region: process.env.AWS_REGION!,
  });

  const result = await client.invoke<InferenceResponse>({
    image_key: event.imageKey,
    prompt: event.prompt,
    max_tokens: 2048,
  });

  if (!result.success) {
    throw new Error(`Inference failed: ${result.error}`);
  }

  return {
    statusCode: 200,
    body: result.data,
    inferenceId: result.inferenceId,
  };
};
```

## Auto-Scaling Configuration

Scale to zero when idle (cost optimization):

```typescript
import * as applicationautoscaling from 'aws-cdk-lib/aws-applicationautoscaling';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import { Duration } from 'aws-cdk-lib';

const scalingTarget = new applicationautoscaling.ScalableTarget(this, 'ScalingTarget', {
  serviceNamespace: applicationautoscaling.ServiceNamespace.SAGEMAKER,
  resourceId: `endpoint/${endpoint.attrEndpointName}/variant/AllTraffic`,
  scalableDimension: 'sagemaker:variant:DesiredInstanceCount',
  minCapacity: 0,  // Scale to zero!
  maxCapacity: 5,
});

// Scale based on queue depth
scalingTarget.scaleToTrackMetric('QueueScaling', {
  targetValue: 5,  // 5 requests per instance
  customMetric: new cloudwatch.Metric({
    namespace: 'AWS/SageMaker',
    metricName: 'ApproximateBacklogSizePerInstance',
    dimensionsMap: {
      EndpointName: endpoint.attrEndpointName,
    },
    statistic: 'Average',
  }),
  scaleInCooldown: Duration.minutes(10),
  scaleOutCooldown: Duration.minutes(2),
});
```

## Error Handling

### Common Failure Modes

| Error | Cause | Solution |
|-------|-------|----------|
| `ModelError` | Model crashed | Check CloudWatch logs, increase instance size |
| `Timeout` | Inference too slow | Increase `InvocationTimeoutSeconds` |
| `NoSuchKey` on poll | Still processing | Increase poll duration |
| `AccessDenied` | IAM permissions | Add S3/SageMaker permissions |

### Retry Strategy

```typescript
async invokeWithRetry<T>(
  payload: object,
  maxRetries: number = 3
): Promise<AsyncInferenceResult<T>> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const result = await this.invoke<T>(payload);

      if (result.success) {
        return result;
      }

      // Only retry timeout-related or transient errors
      if (this.isRetryableError(result.error)) {
        lastError = new Error(result.error);
        await this.sleep(Math.pow(2, attempt) * 1000);  // Exponential backoff
        continue;
      }

      // Non-retryable error (model errors, validation failures, etc.)
      return result;
    } catch (e) {
      lastError = e as Error;
      await this.sleep(Math.pow(2, attempt) * 1000);
    }
  }

  return {
    success: false,
    error: `Max retries exceeded: ${lastError?.message}`,
    inferenceId: 'retry-failed',
  };
}

private isRetryableError(error?: string): boolean {
  if (!error) return false;
  const retryablePatterns = [
    'Timeout',
    'ServiceUnavailable',
    'ThrottlingException',
    'InternalServerError',
    'RequestTimeout',
  ];
  return retryablePatterns.some(pattern => error.includes(pattern));
}
```

## Cost Optimization

| Strategy | Savings | Trade-off |
|----------|---------|-----------|
| Scale to zero | 60-90% | Cold start latency |
| Spot instances | 50-70% | Interruption risk |
| Smaller instance + longer timeout | 30-50% | Slower responses |
| Batch multiple requests | 20-40% | Complexity |

## Monitoring

Key CloudWatch metrics:
- `Invocations` - Request count
- `InvocationModelErrors` - Model failures
- `ApproximateBacklogSize` - Queue depth
- `ModelLatency` - Processing time
- `OverheadLatency` - S3 I/O overhead
