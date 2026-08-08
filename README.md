# AWS Cloud Cost Optimization – Automated EBS Snapshot Cleanup

An automated AWS cost-optimization system that identifies stale/orphaned EBS snapshots, deletes unnecessary snapshots, protects production snapshots, and sends a report by email. The cleanup runs automatically once every week.

## Table of Contents

- [Problem](#problem)
- [Cleanup Rule](#cleanup-rule)
- [AWS Services Used](#aws-services-used)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
  - [1. EventBridge Scheduler](#1-eventbridge-scheduler)
  - [2. Lambda Setup](#2-lambda-setup)
  - [3. SNS Topic ARN](#3-sns-topic-arn)
  - [4. Fetching Snapshots](#4-fetching-snapshots)
  - [5. Processing Each Snapshot](#5-processing-each-snapshot)
  - [6. Production Protection](#6-production-protection)
  - [7. Volume Existence Check](#7-volume-existence-check)
  - [8. Error Handling](#8-error-handling)
  - [9. Tracking Results](#9-tracking-results)
  - [10. SNS Notification](#10-sns-notification)
- [Sample Email Report](#sample-email-report)
- [IAM Permissions](#iam-permissions)
- [CloudWatch Logging](#cloudwatch-logging)
- [Cost Savings](#cost-savings)
- [Concepts Demonstrated](#concepts-demonstrated)
- [60-Second Interview Answer](#60-second-interview-answer)

## Problem

EBS snapshots are stored in Amazon S3-backed snapshot storage and continue to incur storage costs even after the original EBS volume has been deleted.

**Before volume deletion:**

```
EC2 Instance
     │
     ▼
EBS Volume
     │
     ├── Snapshot 1
     ├── Snapshot 2
     └── Snapshot 3
```

**After someone deletes the EBS volume:**

```
EC2 Instance
     │
     X
EBS Volume → DELETED

Snapshots
   ├── Snapshot 1
   ├── Snapshot 2
   └── Snapshot 3
```

The snapshots can still exist and may no longer be useful, but they continue generating storage costs. This project automates the identification and cleanup of those snapshots.

## Cleanup Rule

```
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
```

- **`env=prod`** → the snapshot is protected and always kept, even if its source volume no longer exists.
- **Not `env=prod`** → the Lambda checks the source volume:
  - Volume exists → **KEEP**
  - Volume doesn't exist → **DELETE**

## AWS Services Used

| AWS Service | Purpose |
|---|---|
| AWS Lambda | Runs the cleanup Python code |
| Amazon EC2 / EBS | Provides snapshots and volumes that Lambda examines |
| Amazon EventBridge Scheduler | Runs Lambda automatically every week |
| Amazon SNS | Sends the cleanup report |
| IAM | Gives Lambda permission to access EC2/EBS and SNS |
| CloudWatch Logs | Stores Lambda execution logs |
| Python + boto3 | Implements the automation |

## Architecture

```
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
```

IAM controls Lambda's access to these AWS services, while CloudWatch Logs records what Lambda did.

## How It Works

### 1. EventBridge Scheduler

An Amazon EventBridge Scheduler runs the Lambda once every week, so cleanup doesn't rely on manual execution.

```
Monday / scheduled day
        │
        ▼
EventBridge
        │
        ▼
Lambda automatically executes
```

This matters because cost optimization should ideally be automated rather than relying on someone remembering to run cleanup manually.

### 2. Lambda Setup

The Lambda is written in Python using `boto3`, the AWS SDK for Python, to communicate with EC2/EBS and SNS.

```python
import os
import boto3
from botocore.exceptions import ClientError

ec2 = boto3.client("ec2")
sns = boto3.client("sns", region_name="ap-northeast-2")
```

This lets Python call AWS APIs such as:

```python
ec2.describe_snapshots()
ec2.describe_volumes()
ec2.delete_snapshot()
sns.publish()
```

### 3. SNS Topic ARN

The SNS ARN isn't hardcoded into the Python logic. Instead, it's read from a Lambda environment variable:

```python
TOPIC_ARN = os.environ["TOPIC_ARN"]
```

```
Lambda Environment Variable
     TOPIC_ARN
        │
        ▼
   SNS Topic ARN
        │
        ▼
   sns.publish()
```

### 4. Fetching Snapshots

```python
response = ec2.describe_snapshots(
    OwnerIds=["self"]
)
```

This asks AWS for the EBS snapshots owned by the account, returned in `response["Snapshots"]`.

### 5. Processing Each Snapshot

```python
for snapshot in response["Snapshots"]:
    snapshot_id = snapshot["SnapshotId"]
    volume_id = snapshot.get("VolumeId")
```

Each snapshot is linked to its source volume, e.g. `snap-123` → `vol-456`.

### 6. Production Protection

A tag-based protection mechanism checks for `env=prod`:

```python
tags = snapshot.get("Tags", [])

env_prod = any(
    tag["Key"] == "env" and tag["Value"] == "prod"
    for tag in tags
)

if env_prod:
    ...
    continue
```

Production-tagged snapshots are immediately kept, since automated deletion of a production backup is dangerous.

### 7. Volume Existence Check

For non-production snapshots without a volume ID:

```python
if not volume_id:
    ...
```

This prevents Lambda from blindly calling `describe_volumes()` with an invalid value.

For snapshots with a volume ID, Lambda checks whether the source volume still exists:

```python
ec2.describe_volumes(
    VolumeIds=[volume_id]
)
```

- **Volume exists** → AWS successfully returns the volume → snapshot is added to `kept_snapshots`.
- **Volume doesn't exist** → AWS raises `InvalidVolume.NotFound` → snapshot is deleted:

```python
ec2.delete_snapshot(
    SnapshotId=snapshot_id
)
```

### 8. Error Handling

AWS API calls can fail (e.g. `describe_volumes()` raising `InvalidVolume.NotFound`). Instead of letting Lambda crash, the code catches the exception and checks the specific error code:

```python
except ClientError as e:
    if e.response["Error"]["Code"] == "InvalidVolume.NotFound":
        ...
```

### 9. Tracking Results

Two lists track the outcome of each run:

```python
deleted_snapshots = []
kept_snapshots = []
```

Example entries:

```
snap-111 - KEPT - env=prod
snap-222 - KEPT - Volume exists
snap-333 - DELETED - Volume vol-333 no longer exists
```

These lists feed directly into the SNS report.

### 10. SNS Notification

An email is sent on every execution, not only when something gets deleted:

```python
sns.publish(
    TopicArn=TOPIC_ARN,
    Subject="EBS Snapshot Cleanup Report",
    Message=message
)
```

```
Snapshots deleted?
       │
   ┌───┴───┐
  YES      NO
   │        │
   └───┬────┘
       │
       ▼
  Send SNS email
```

Even with 0 snapshots deleted, a report is still sent.

## Sample Email Report

```
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
```

## IAM Permissions

The Lambda execution role requires:

- `ec2:DescribeSnapshots`
- `ec2:DescribeVolumes`
- `ec2:DeleteSnapshot`
- `sns:Publish`

```
Lambda
   │
   ▼
IAM Execution Role
   │
   ├── DescribeSnapshots
   ├── DescribeVolumes
   ├── DeleteSnapshot
   └── SNS Publish
```

Without these permissions, Lambda receives `UnauthorizedOperation` (encountered previously with `DescribeInstances`).

## CloudWatch Logging

Lambda automatically sends execution logs to CloudWatch Logs via `print()` statements:

```python
print(f"Checking {snapshot_id}")
print(f"Keeping {snapshot_id} because env=prod")
print(f"Deleting {snapshot_id}")
```

Example log output:

```
Checking snap-111
Keeping snap-111 because env=prod

Checking snap-222
Keeping snap-222 - Volume exists

Checking snap-333
Deleting snap-333 - Volume no longer exists

SNS notification sent successfully.
```

## Cost Savings

**Before automation:**

```
Orphaned snapshots
       ↓
Storage consumed
       ↓
Unnecessary cost
```

**After automation:**

```
Weekly EventBridge
       ↓
Lambda cleanup
       ↓
Orphaned snapshots removed
       ↓
Less snapshot storage
       ↓
Lower AWS cost
```

## Concepts Demonstrated

- AWS: EC2, EBS, Lambda, IAM, SNS, EventBridge Scheduler, CloudWatch
- Python + boto3
- Exception handling, lists, loops, conditional logic
- Environment variables
- DevOps automation and scheduled jobs
- Cost optimization and resource cleanup
- Monitoring/logging and notifications
- Least-privilege IAM and safety controls

## 60-Second Interview Answer

> I built an automated AWS cost optimization system for EBS snapshots. The main problem I wanted to solve was stale snapshots that remain after their source EBS volumes have been deleted and continue contributing to storage costs.
>
> I use EventBridge Scheduler to trigger an AWS Lambda function once every week. The Lambda is written in Python using boto3. It retrieves all EBS snapshots owned by the account and processes them individually.
>
> I added a safety mechanism using the `env=prod` tag. If a snapshot is tagged as production, the Lambda protects it from automated deletion. For other snapshots, it checks whether the source EBS volume still exists using the EC2 API. If AWS returns `InvalidVolume.NotFound`, I consider the snapshot stale and delete it.
>
> I maintain lists of kept and deleted snapshots and generate a cleanup report. The report is sent through an SNS topic to my email after every execution, even if no snapshots were deleted. Lambda execution logs are available in CloudWatch, and IAM permissions control the Lambda's access to EC2, EBS, and SNS.
