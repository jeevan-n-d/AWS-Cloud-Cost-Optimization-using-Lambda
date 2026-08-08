import os
import boto3
from botocore.exceptions import ClientError

ec2 = boto3.client("ec2")
sns = boto3.client("sns")

TOPIC_ARN = os.environ["TOPIC_ARN"]


def lambda_handler(event, context):

    response = ec2.describe_snapshots(OwnerIds=["self"])

    deleted_snapshots = []

    for snapshot in response["Snapshots"]:

        snapshot_id = snapshot["SnapshotId"]
        volume_id = snapshot.get("VolumeId")

        print(f"Checking {snapshot_id}")

        # Check snapshot tag
        tags = snapshot.get("Tags", [])

        env_prod = any(
            tag["Key"] == "env" and tag["Value"] == "prod"
            for tag in tags
        )

        # Keep production snapshots
        if env_prod:
            print(f"Keeping {snapshot_id} because env=prod")
            continue

        try:

            # Check if volume exists
            ec2.describe_volumes(
                VolumeIds=[volume_id]
            )

        except ClientError as e:

            # Volume already deleted
            if e.response["Error"]["Code"] == "InvalidVolume.NotFound":

                ec2.delete_snapshot(
                    SnapshotId=snapshot_id
                )

                deleted_snapshots.append(snapshot_id)

                print(f"Deleted {snapshot_id}")

    # Send Email
    if deleted_snapshots:

        message = "Deleted Snapshots:\n\n"

        for snapshot in deleted_snapshots:
            message += snapshot + "\n"

        sns.publish(
            TopicArn=TOPIC_ARN,
            Subject="EBS Snapshot Cleanup Report",
            Message=message
        )

        print("SNS Notification Sent")

    else:

        print("No snapshots deleted.")

    return {
        "statusCode": 200,
        "DeletedSnapshots": deleted_snapshots
    }
