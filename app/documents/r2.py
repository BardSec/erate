import os
import uuid
import boto3
from flask import current_app
from botocore.config import Config as BotoConfig


def _get_s3_client():
    """Get S3 client configured for R2, or None if not configured."""
    endpoint = current_app.config.get('R2_ENDPOINT_URL', '')
    access_key = current_app.config.get('R2_ACCESS_KEY_ID', '')
    secret_key = current_app.config.get('R2_SECRET_ACCESS_KEY', '')

    if not all([endpoint, access_key, secret_key]):
        return None

    return boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=BotoConfig(signature_version='s3v4'),
        region_name='auto',
    )


def _get_bucket():
    return current_app.config.get('R2_BUCKET_NAME', 'erate-documents')


def generate_r2_key(tenant_id, category, original_filename):
    """Generate a unique R2 key for a document."""
    ext = os.path.splitext(original_filename)[1] if '.' in original_filename else ''
    unique = uuid.uuid4().hex[:12]
    return f'tenants/{tenant_id}/{category}/{unique}{ext}'


def upload_file(file_obj, r2_key, content_type='application/octet-stream'):
    """Upload a file to R2 or local filesystem fallback."""
    client = _get_s3_client()
    if client:
        client.upload_fileobj(
            file_obj,
            _get_bucket(),
            r2_key,
            ExtraArgs={'ContentType': content_type},
        )
        return True

    # Local filesystem fallback
    upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    local_path = os.path.join(upload_dir, r2_key)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    file_obj.save(local_path)
    return True


def get_presigned_download_url(r2_key, expires_in=3600):
    """Get a presigned URL for downloading a file."""
    client = _get_s3_client()
    if client:
        return client.generate_presigned_url(
            'get_object',
            Params={'Bucket': _get_bucket(), 'Key': r2_key},
            ExpiresIn=expires_in,
        )
    # Local fallback - return a route URL
    return None


def get_presigned_upload_url(r2_key, content_type='application/octet-stream', expires_in=3600):
    """Get a presigned URL for uploading a file."""
    client = _get_s3_client()
    if client:
        return client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': _get_bucket(),
                'Key': r2_key,
                'ContentType': content_type,
            },
            ExpiresIn=expires_in,
        )
    return None


def delete_file(r2_key):
    """Delete a file from R2 or local filesystem."""
    client = _get_s3_client()
    if client:
        client.delete_object(Bucket=_get_bucket(), Key=r2_key)
        return True

    upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    local_path = os.path.join(upload_dir, r2_key)
    if os.path.exists(local_path):
        os.remove(local_path)
    return True


def get_local_file_path(r2_key):
    """Get the local filesystem path for a file (fallback mode)."""
    upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    return os.path.join(upload_dir, r2_key)
