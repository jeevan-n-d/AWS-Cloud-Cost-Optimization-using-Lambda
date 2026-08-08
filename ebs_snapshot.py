import os
import boto3
from botocore.exceptions import ClientError

ec2 = boto3.client("ec2")
sns = boto3.client("sns", region_name="ap-northeast-2")

TOPIC_ARN = os.environ["TOPIC_ARN"]


def lambda_handler(event, context):

    response = ec2.describe_snapshots(OwnerIds=["self"])

    deleted_snapshots = []
    kept_snapshots = []

    for snapshot in response["Snapshots"]:

        snapshot_id = snapshot["SnapshotId"]
        volume_id = snapshot.get("VolumeId")

        print(f"Checking {snapshot_id}")

        # Get snapshot tags
        tags = snapshot.get("Tags", [])

        env_prod = any(
            tag["Key"] == "env" and tag["Value"] == "prod"
            for tag in tags
        )

        # ----------------------------------------
        # NEVER DELETE PRODUCTION SNAPSHOTS
        # ----------------------------------------

        if env_prod:

            kept_snapshots.append(
                f"{snapshot_id} - KEPT - env=prod"
            )

            print(
                f"Keeping {snapshot_id} because env=prod"
            )

            continue

        # ----------------------------------------
        # Check VolumeId
        # ----------------------------------------

        if not volume_id:

            print(
                f"Deleting {snapshot_id} - "
                f"VolumeId is missing"
            )

            try:

                ec2.delete_snapshot(
                    SnapshotId=snapshot_id
                )

                deleted_snapshots.append(
                    f"{snapshot_id} - DELETED - VolumeId missing"
                )

            except ClientError as e:

                print(
                    f"Could not delete {snapshot_id}: {e}"
                )

            continue

        # ----------------------------------------
        # Check whether source volume exists
        # ----------------------------------------

        try:

            ec2.describe_volumes(
                VolumeIds=[volume_id]
            )

            # Volume exists
            kept_snapshots.append(
                f"{snapshot_id} - KEPT - "
                f"Volume {volume_id} exists"
            )

            print(
                f"Keeping {snapshot_id} - "
                f"Volume {volume_id} exists"
            )

        except ClientError as e:

            # Source volume does not exist
            if e.response["Error"]["Code"] == "InvalidVolume.NotFound":

                print(
                    f"Deleting {snapshot_id} - "
                    f"Volume {volume_id} no longer exists"
                )

                try:

                    ec2.delete_snapshot(
                        SnapshotId=snapshot_id
                    )

                    deleted_snapshots.append(
                        f"{snapshot_id} - DELETED - "
                        f"Volume {volume_id} no longer exists"
                    )

                except ClientError as delete_error:

                    print(
                        f"Could not delete "
                        f"{snapshot_id}: {delete_error}"
                    )

            else:

                print(
                    f"Error checking volume "
                    f"{volume_id}: {e}"
                )

                kept_snapshots.append(
                    f"{snapshot_id} - ERROR - "
                    f"Could not check volume"
                )

    # ============================================
    # CREATE EMAIL REPORT
    # ============================================

    message = "AWS EBS Snapshot Cleanup Report\n"
    message += "================================\n\n"

    message += (
        f"Total Snapshots Checked: "
        f"{len(response['Snapshots'])}\n"
    )

    message += (
        f"Total Snapshots Kept: "
        f"{len(kept_snapshots)}\n"
    )

    message += (
        f"Total Snapshots Deleted: "
        f"{len(deleted_snapshots)}\n\n"
    )

    # --------------------------------------------
    # KEPT SNAPSHOTS
    # --------------------------------------------

    message += "KEPT SNAPSHOTS\n"
    message += "--------------\n"

    if kept_snapshots:

        for snapshot in kept_snapshots:
            message += snapshot + "\n"

    else:

        message += "No snapshots were kept.\n"

    # --------------------------------------------
    # DELETED SNAPSHOTS
    # --------------------------------------------

    message += "\nDELETED SNAPSHOTS\n"
    message += "----------------\n"

    if deleted_snapshots:

        for snapshot in deleted_snapshots:
            message += snapshot + "\n"

    else:

        message += "No snapshots were deleted.\n"

    # ============================================
    # ALWAYS SEND SNS EMAIL
    # ============================================

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="EBS Snapshot Cleanup Report",
        Message=message
    )

    print("SNS notification sent successfully.")

    # ============================================
    # LAMBDA RESPONSE
    # ============================================

    return {
        "statusCode": 200,
        "TotalSnapshots": len(response["Snapshots"]),
        "DeletedSnapshots": deleted_snapshots,
        "KeptSnapshots": kept_snapshots
    }
