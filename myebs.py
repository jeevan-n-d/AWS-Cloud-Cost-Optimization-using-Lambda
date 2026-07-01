import boto3

ec2 = boto3.client('ec2')
sns = boto3.client('sns')

TOPIC_ARN = "arn:aws:sns:ap-south-1:931628308792:snapshot-alerts"

def lambda_handler(event, context):

    response = ec2.describe_snapshots(OwnerIds=['self'])

    deleted_snapshots = []

    for snapshot in response['Snapshots']:

        snapshot_id = snapshot['SnapshotId']
        volume_id = snapshot.get('VolumeId')

        try:

            if not volume_id:

                ec2.delete_snapshot(SnapshotId=snapshot_id)

                deleted_snapshots.append(snapshot_id)

            else:

                volume_response = ec2.describe_volumes(
                    VolumeIds=[volume_id]
                )

                if not volume_response['Volumes'][0]['Attachments']:

                    ec2.delete_snapshot(SnapshotId=snapshot_id)

                    deleted_snapshots.append(snapshot_id)

        except Exception as e:

            print(f"Error processing snapshot {snapshot_id}: {str(e)}")

    # Send SNS notification
    if deleted_snapshots:

        message = "Deleted Snapshots:\n\n"

        for snap in deleted_snapshots:
            message += f"{snap}\n"

        sns.publish(
            TopicArn=TOPIC_ARN,
            Subject='EBS Snapshot Cleanup Report',
            Message=message
        )

    return {
        'statusCode': 200,
        'body': 'Snapshot cleanup completed'
    }
