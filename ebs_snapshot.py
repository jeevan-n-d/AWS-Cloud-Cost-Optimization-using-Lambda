import os
import boto3
from botocore.exceptions import ClientError

ec2 = boto3.client("ec2")
sns = boto3.client("sns", region_name="ap-south-1")

TOPIC_ARN = os.environ["TOPIC_ARN"]


def lambda_handler(event, context):

    response = ec2.describe_snapshots(OwnerIds=["self"])

    deleted_snapshots = []
    kept_snapshots = []

    for snapshot in response["Snapshots"]:

        snapshot_id = snapshot["SnapshotId"]
        volume_id = snapshot.get("VolumeId")

        print(f"Checking {snapshot_id}")

        # Get tags
        tags = snapshot.get("Tags", [])

        env_prod = any(
            tag["Key"] == "env" and tag["Value"] == "prod"
            for tag in tags
        )

        # If VolumeId is missing
        if not volume_id:

            print(
                f"Deleting {snapshot_id} "
                f"because VolumeId is missing"
            )

            ec2.delete_snapshot(
                SnapshotId=snapshot_id
            )

            deleted_snapshots.append(
                f"{snapshot_id} - VolumeId missing"
            )

            continue

        try:

            # Check whether source volume exists
            ec2.describe_volumes(
                VolumeIds=[volume_id]
            )

            # Volume exists
            if env_prod:

                reason = "Volume exists, env=prod"

            else:

                reason = "Volume exists"

            kept_snapshots.append(
                f"{snapshot_id} - KEPT - {reason}"
            )

            print(
                f"Keeping {snapshot_id} - {reason}"
            )

        except ClientError as e:

            # Source volume does not exist
            if e.response["Error"]["Code"] == "InvalidVolume.NotFound":

                print(
                    f"Deleting {snapshot_id} because "
                    f"volume {volume_id} no longer exists"
                )

                ec2.delete_snapshot(
                    SnapshotId=snapshot_id
                )

                deleted_snapshots.append(
                    f"{snapshot_id} - Volume {volume_id} no longer exists"
                )

            else:

                print(
                    f"Error checking volume {volume_id}: {e}"
                )

    # Create notification
    message = "AWS EBS Snapshot Cleanup Report\n\n"

    # Existing / kept snapshots
    message += "EXISTING SNAPSHOTS:\n"
    message += "-------------------\n"

    if kept_snapshots:

        for snapshot in kept_snapshots:
            message += snapshot + "\n"

    else:

        message += "No snapshots were kept.\n"

    # Deleted snapshots
    message += "\nDELETED SNAPSHOTS:\n"
    message += "------------------\n"

    if deleted_snapshots:

        for snapshot in deleted_snapshots:
            message += snapshot + "\n"

    else:

        message += "No snapshots were deleted.\n"

    # Send SNS notification
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="EBS Snapshot Cleanup Report",
        Message=message
    )

    print("SNS Notification Sent")

    return {
        "statusCode": 200,
        "DeletedSnapshots": deleted_snapshots,
        "KeptSnapshots": kept_snapshots
    }
