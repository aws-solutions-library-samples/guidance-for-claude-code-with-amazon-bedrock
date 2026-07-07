# ABOUTME: Sanity check that index.py imports cleanly under moto mocking
# ABOUTME: Catches issues like missing env vars or broken module-level boto3 client creation


def test_index_imports(idx):
    assert idx.BUCKET_NAME == 'test-bucket'
    assert hasattr(idx, 'lambda_handler')


def test_bucket_fixture_creates_bucket(idx, bucket):
    import boto3
    s3 = boto3.client('s3', region_name='us-east-1')
    resp = s3.list_buckets()
    names = [b['Name'] for b in resp['Buckets']]
    assert bucket in names
