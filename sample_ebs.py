import os
import boto3
from botocore.exceptions import ClientError

ec2 = boto3.client("ec2")
sns = boto3.client("sns")

TOPIC_ARN = os.environ["TOPIC_ARN"]


def lambda_handler(event, context):

    response = ec2.describe_snapshots(OwnerIds=["self"])

    kept = []
    deleted = []

    for snapshot in response["Snapshots"]:

        snapshot_id = snapshot["SnapshotId"]
        volume_id = snapshot.get("VolumeId")

        tags = snapshot.get("Tags", [])
        env_prod = any(
            tag["Key"] == "env" and tag["Value"] == "prod"
            for tag in tags
        )

        try:
            ec2.describe_volumes(VolumeIds=[volume_id])

            reason = "Volume exists"

            if env_prod:
                reason += ", env=prod"

            kept.append(f"{snapshot_id} - {reason}")

        except ClientError as e:

            if e.response["Error"]["Code"] == "InvalidVolume.NotFound":

                ec2.delete_snapshot(
                    SnapshotId=snapshot_id
                )

                deleted.append(
                    f"{snapshot_id} - Volume {volume_id} not found"
                )

            else:
                print(f"Error checking {snapshot_id}: {e}")

    # Create email report
    message = "EBS Snapshot Cleanup Report\n\n"

    message += "KEPT SNAPSHOTS:\n"
    for snapshot in kept:
        message += snapshot + "\n"

    message += "\nDELETED SNAPSHOTS:\n"
    for snapshot in deleted:
        message += snapshot + "\n"

    # Send email EVERY execution
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="EBS Snapshot Cleanup Report",
        Message=message
    )

    return {
        "statusCode": 200,
        "kept": kept,
        "deleted": deleted
    }
