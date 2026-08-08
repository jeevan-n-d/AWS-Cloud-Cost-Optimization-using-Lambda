AWS Cloud Cost Optimization – Automated EBS Snapshot Cleanup

Your project is an automated AWS cost-optimization system that identifies stale/orphaned EBS snapshots, deletes unnecessary snapshots, protects production snapshots, and sends a report by email. The cleanup runs automatically once every week.

1. Problem you're solving

EBS snapshots are stored in Amazon S3-backed snapshot storage and continue to incur storage costs even after the original EBS volume has been deleted.

For example:

EC2 Instance
     │
     ▼
EBS Volume
     │
     ├── Snapshot 1
     ├── Snapshot 2
     └── Snapshot 3

Later, someone deletes the EBS volume:

EC2 Instance
     │
     X
EBS Volume → DELETED

Snapshots
   ├── Snapshot 1
   ├── Snapshot 2
   └── Snapshot 3

The snapshots can still exist.

Those snapshots may no longer be useful, but they can continue generating storage costs.

Your project automates the identification and cleanup of those snapshots.

2. Your actual cleanup rule

Your Lambda follows this logic:

                 EBS Snapshot
                      │
                      ▼
                env=prod?
                 /       \
               YES        NO
                │          │
                ▼          ▼
              KEEP     Source Volume
                         exists?
                         /     \
                       YES      NO
                        │        │
                        ▼        ▼
                      KEEP     DELETE

So:

env=prod

The snapshot is protected.

env=prod → KEEP

Even if its source volume no longer exists.

Not env=prod

The Lambda checks the source volume.

Volume exists → KEEP

Volume doesn't exist → DELETE

This is your project's actual behavior.

3. AWS services you used

You have used these AWS services/components:

AWS Service	Purpose
AWS Lambda	Runs your cleanup Python code
Amazon EC2 / EBS	Provides snapshots and volumes that Lambda examines
Amazon EventBridge Scheduler	Runs Lambda automatically every week
Amazon SNS	Sends cleanup report
IAM	Gives Lambda permission to access EC2/EBS and SNS
CloudWatch Logs	Stores Lambda execution logs
Python + boto3	Implements the automation

So your architecture is:

             EventBridge Scheduler
                    │
                 Weekly
                    │
                    ▼
              AWS Lambda
              Python/boto3
                    │
                    ▼
             EC2 / EBS API
                    │
             Get Snapshots
                    │
                    ▼
              Check each one
                    │
           ┌────────┴────────┐
           │                 │
       env=prod?          Not prod
           │                 │
          YES                ▼
           │          Check EBS Volume
           │             /         \
           │          Exists      Missing
           │            │            │
           ▼            ▼            ▼
         KEEP         KEEP         DELETE
                                      │
                                      ▼
                                  SNS Topic
                                      │
                                      ▼
                                    Email
4. EventBridge Scheduler

You created an Amazon EventBridge Scheduler to run the Lambda once every week.

So you don't manually execute Lambda.

Instead:

Monday / scheduled day
        │
        ▼
EventBridge
        │
        ▼
Lambda automatically executes

This is important because cost optimization should ideally be automated, rather than relying on someone remembering to run cleanup manually.

5. Lambda

Your Lambda contains Python code using boto3.

At the beginning:

import os
import boto3
from botocore.exceptions import ClientError
boto3

Boto3 is the AWS SDK for Python.

You're using it to communicate with:

EC2/EBS
SNS

You create clients:

ec2 = boto3.client("ec2")
sns = boto3.client("sns", region_name="ap-northeast-2")

So Python can call AWS APIs such as:

ec2.describe_snapshots()
ec2.describe_volumes()
ec2.delete_snapshot()
sns.publish()
6. SNS Topic ARN

You didn't hardcode your SNS ARN directly into the Python logic.

You use:

TOPIC_ARN = os.environ["TOPIC_ARN"]

You configured the ARN as a Lambda environment variable.

That's better practice than putting the ARN directly into your source code.

Your architecture is:

Lambda Environment Variable

TOPIC_ARN
     │
     ▼
SNS Topic ARN
     │
     ▼
sns.publish()
7. Lambda gets all snapshots

Your code starts with:

response = ec2.describe_snapshots(
    OwnerIds=["self"]
)

This tells AWS:

"Give me the EBS snapshots owned by my AWS account."

Then:

response["Snapshots"]

contains the snapshots.

For example:

snap-111
snap-222
snap-333
8. Lambda processes every snapshot

You use:

for snapshot in response["Snapshots"]:

So Lambda processes each snapshot individually.

For every snapshot, you get:

snapshot_id = snapshot["SnapshotId"]
volume_id = snapshot.get("VolumeId")

For example:

Snapshot ID:
snap-123

Source Volume:
vol-456

The relationship is:

Snapshot
snap-123
    │
    ▼
Source EBS Volume
vol-456
9. Production protection

You added a tag-based protection mechanism.

Your snapshot might have:

Key:   env
Value: prod

Your code checks:

tags = snapshot.get("Tags", [])

env_prod = any(
    tag["Key"] == "env" and tag["Value"] == "prod"
    for tag in tags
)

If it is production:

if env_prod:
    ...
    continue

The snapshot is immediately kept.

Why?

Because automated deletion of a production backup is dangerous.

Your project therefore has a safety mechanism:

env=prod
   ↓
PROTECTED
10. Check whether VolumeId exists

For non-production snapshots, your Lambda checks:

if not volume_id:

If there is no Volume ID, your code handles that case and attempts cleanup.

This prevents the Lambda from blindly trying to call describe_volumes() with an invalid value.

11. Check whether the source volume exists

This is the core of your cost optimization logic:

ec2.describe_volumes(
    VolumeIds=[volume_id]
)

You're asking AWS:

"Does this EBS volume still exist?"

Case 1 — Volume exists

AWS successfully returns the volume.

Snapshot
   │
   ▼
Volume exists
   │
   ▼
KEEP SNAPSHOT

You add it to:

kept_snapshots
12. Case 2 — Volume doesn't exist

Suppose:

Snapshot
snap-123
     │
     ▼
Volume
vol-456
     X
   deleted

Lambda calls:

ec2.describe_volumes(
    VolumeIds=["vol-456"]
)

AWS returns:

InvalidVolume.NotFound

Your code catches the AWS error:

except ClientError as e:

Then checks:

if e.response["Error"]["Code"] == "InvalidVolume.NotFound":

This confirms:

The source volume no longer exists.

Then:

ec2.delete_snapshot(
    SnapshotId=snapshot_id
)

The stale snapshot is deleted.

13. Why you use ClientError

AWS API calls can fail.

For example:

describe_volumes()
       ↓
AWS
       ↓
InvalidVolume.NotFound

Instead of allowing Lambda to crash, your code catches the AWS exception:

except ClientError as e:

Then you specifically check the error code.

That's good AWS/Python practice.

14. You maintain two lists

You created:

deleted_snapshots = []
kept_snapshots = []
Kept

Example:

snap-111 - KEPT - env=prod
snap-222 - KEPT - Volume exists
Deleted

Example:

snap-333 - DELETED - Volume vol-333 no longer exists

These lists are then used to create your SNS report.

15. SNS notification

You wanted an email every time Lambda executes, not only when something gets deleted.

So your code always executes:

sns.publish(
    TopicArn=TOPIC_ARN,
    Subject="EBS Snapshot Cleanup Report",
    Message=message
)

This means:

Snapshots deleted?
       │
   ┌───┴───┐
  YES      NO
   │        │
   └───┬────┘
       │
       ▼
  Send SNS email

Even if:

0 snapshots deleted

you still receive the report.

16. Your email report

Your email contains:

AWS EBS Snapshot Cleanup Report

Total Snapshots Checked: 5
Total Snapshots Kept: 4
Total Snapshots Deleted: 1

KEPT SNAPSHOTS
--------------
snap-111 - KEPT - env=prod
snap-222 - KEPT - Volume vol-222 exists
snap-333 - KEPT - Volume vol-333 exists
snap-444 - KEPT - env=prod

DELETED SNAPSHOTS
----------------
snap-555 - DELETED - Volume vol-555 no longer exists

This is useful because you can see what the automation actually did.

17. IAM

Your Lambda needs permissions to perform these operations.

The important permissions are:

ec2:DescribeSnapshots
ec2:DescribeVolumes
ec2:DeleteSnapshot
sns:Publish

Your Lambda assumes its execution role:

Lambda
   │
   ▼
IAM Execution Role
   │
   ├── DescribeSnapshots
   ├── DescribeVolumes
   ├── DeleteSnapshot
   └── SNS Publish

Without these permissions, Lambda would receive:

UnauthorizedOperation

which you actually encountered earlier with DescribeInstances.

18. CloudWatch

Lambda automatically sends its execution logs to CloudWatch Logs.

Your code contains:

print(f"Checking {snapshot_id}")

and:

print(f"Keeping {snapshot_id} because env=prod")

and:

print(f"Deleting {snapshot_id}")

So you can open CloudWatch and see what happened during each weekly execution.

Example:

Checking snap-111
Keeping snap-111 because env=prod

Checking snap-222
Keeping snap-222 - Volume exists

Checking snap-333
Deleting snap-333 - Volume no longer exists

SNS notification sent successfully.
19. Why this saves money

Imagine you have:

10 orphaned snapshots
×
snapshot storage cost
×
months

Those snapshots continue consuming snapshot storage.

Your Lambda automatically identifies snapshots whose source volumes have been deleted and removes them.

So:

Before automation

Orphaned snapshots
       ↓
Storage consumed
       ↓
Unnecessary cost

After automation:

Weekly EventBridge
       ↓
Lambda cleanup
       ↓
Orphaned snapshots removed
       ↓
Less snapshot storage
       ↓
Lower AWS cost
20. What you have actually demonstrated

This isn't just a Lambda project.

You've demonstrated:

AWS
EC2
EBS
Lambda
IAM
SNS
EventBridge Scheduler
CloudWatch
Python
boto3
Exception handling
Lists
Loops
Conditional logic
Environment variables
DevOps concepts
Automation
Scheduled jobs
Cost optimization
Resource cleanup
Monitoring/logging
Notifications
Least-privilege IAM
Safety controls
21. Your final architecture

This is the diagram I'd use when explaining the project:

                    ┌─────────────────────────┐
                    │ EventBridge Scheduler    │
                    │      Every Week          │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │       AWS Lambda        │
                    │     Python + Boto3      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │     EC2 / EBS API       │
                    │                         │
                    │  Get all Snapshots      │
                    │  Check Snapshot Tags    │
                    │  Check EBS Volumes      │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
               env=prod?                 Not prod
                    │                         │
                  KEEP                 Check Volume
                                              │
                                     ┌────────┴────────┐
                                     │                 │
                                  Exists           Not Found
                                     │                 │
                                   KEEP              DELETE
                                                       │
                                                       ▼
                                          ┌────────────────────┐
                                          │     SNS Topic      │
                                          └─────────┬──────────┘
                                                    │
                                                    ▼
                                                 📧 Email

And IAM controls Lambda's access to these AWS services, while CloudWatch Logs records what Lambda did.

22. Interview answer — 60 seconds

If the interviewer says:

"Explain your AWS cost optimization project."

Say:

"I built an automated AWS cost optimization system for EBS snapshots. The main problem I wanted to solve was stale snapshots that remain after their source EBS volumes have been deleted and continue contributing to storage costs.

I use EventBridge Scheduler to trigger an AWS Lambda function once every week. The Lambda is written in Python using boto3. It retrieves all EBS snapshots owned by the account and processes them individually.

I added a safety mechanism using the env=prod tag. If a snapshot is tagged as production, the Lambda protects it from automated deletion. For other snapshots, it checks whether the source EBS volume still exists using the EC2 API. If AWS returns InvalidVolume.NotFound, I consider the snapshot stale and delete it.

I maintain lists of kept and deleted snapshots and generate a cleanup report. The report is sent through an SNS topic to my email after every execution, even if no snapshots were deleted. Lambda execution logs are available in CloudWatch, and IAM permissions control the Lambda's access to EC2, EBS, and SNS."
