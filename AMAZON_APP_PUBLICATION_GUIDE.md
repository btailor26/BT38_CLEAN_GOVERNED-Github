# Amazon SP-API App Publication Guide

## 📋 Overview

This guide helps you publish your Amazon SP-API application to the Amazon Marketplace Appstore. Once published, you can **remove AWS credentials** and use **LWA-only authentication** (no AWS charges!).

---

## 🎯 Two Authentication Modes

### Mode 1: AWS + LWA (Current - Draft App)
- **Status:** Temporary solution for Draft apps
- **Requirements:** AWS IAM credentials + LWA tokens
- **Cost:** AWS Free Tier (6 months free) + minimal charges after
- **Setup Time:** 5-10 minutes
- **Use Case:** Get started immediately while waiting for app approval

### Mode 2: LWA-Only (Goal - Published App)
- **Status:** After app publication approval
- **Requirements:** Only LWA tokens (no AWS!)
- **Cost:** FREE (no AWS charges)
- **Setup Time:** 2-4 weeks (Amazon review process)
- **Use Case:** Long-term production solution

---

## 🚀 Quick Setup: Adding AWS Credentials (Mode 1)

### Step 1: Create AWS IAM User

1. **Go to AWS IAM Console:** https://console.aws.amazon.com/iam/home#/users
2. **Click "Create user"**
   - User name: `sp-api-user`
   - Click **Next**
3. **Set permissions:**
   - Select **"Attach policies directly"**
   - Click **"Create policy"** → **"JSON"** tab
   - Paste this policy:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": "execute-api:Invoke",
       "Resource": "arn:aws:execute-api:*:*:*"
     }]
   }
   ```
   - Click **"Next"** → Name: `sp-api-execute` → **"Create policy"**
   - Go back and select the `sp-api-execute` policy
   - Click **Next** → **Create user**

4. **Create Access Keys:**
   - Click on the user you just created
   - Go to **"Security credentials"** tab
   - Click **"Create access key"**
   - Select **"Application running outside AWS"**
   - Click **"Next"** → **"Create access key"**
   - **SAVE THESE:**
     - Access Key ID: `AKIA...`
     - Secret Access Key: `...`

5. **Get User ARN:**
   - At the top of the user page, copy the **ARN**
   - Example: `arn:aws:iam::123456789012:user/sp-api-user`

### Step 2: Add Credentials to BT38 Store

#### Option A: Via Web UI (Recommended)

1. **Go to:** https://your-app.replit.dev/stores
2. **Click "Edit" on BT38 store**
3. **Update API Key JSON** to include AWS credentials:

```json
{
  "refresh_token": "Atzr|...",
  "lwa_app_id": "amzn1.application-oa2-client...",
  "lwa_client_secret": "amzn1.oa2-cs...",
  "seller_id": "A1F83G8C2ARO7P",
  "marketplace_id": "A1F83G8C2ARO7P",
  "aws_access_key_id": "AKIA...",
  "aws_secret_access_key": "your-secret-key",
  "role_arn": "arn:aws:iam::123456789012:user/sp-api-user"
}
```

4. **Save** and test sync!

#### Option B: Via Database (Advanced)

```sql
UPDATE store 
SET api_key = '{
  "refresh_token": "Atzr|...",
  "lwa_app_id": "amzn1.application-oa2-client...",
  "lwa_client_secret": "amzn1.oa2-cs...",
  "seller_id": "A1F83G8C2ARO7P",
  "marketplace_id": "A1F83G8C2ARO7P",
  "aws_access_key_id": "AKIA...",
  "aws_secret_access_key": "your-secret-key",
  "role_arn": "arn:aws:iam::123456789012:user/sp-api-user"
}'::jsonb
WHERE name = 'BT38';
```

### Step 3: Verify AWS Mode

Check logs for:
```
🔐 Initialized Amazon REST API client (AWS MODE - Draft app)
🔐 Using AWS credentials for Draft app authentication
✅ Successfully authenticated Amazon store: BT38
```

✅ **You're now running in AWS mode!** Your Amazon sync will work immediately.

---

## 📝 Publishing Your App (Mode 2 - Long Term)

### Overview
Publishing your app to Amazon Marketplace Appstore allows you to:
- Remove AWS credentials (no AWS charges!)
- Use LWA-only authentication
- Make your app available to other sellers (optional)

### Publication Process

#### Step 1: Prepare App Information

Before starting, gather:

1. **App Details:**
   - App Name: "BeatsTech Inventory Management System"
   - Description: Multi-channel inventory management with Amazon integration
   - Category: Inventory Management
   - Privacy Policy URL
   - Support Email
   - Support Website

2. **Technical Details:**
   - OAuth Redirect URIs: `https://your-app.replit.dev/amazon/callback`
   - App Type: Private (only for your seller account) or Public
   - Data Usage Description

3. **Screenshots:**
   - Dashboard screenshot
   - Inventory management screenshot
   - At least 3-5 screenshots showing key features

#### Step 2: Submit App for Review

1. **Go to:** https://developer.amazonservices.com/
2. **Sign in** with your seller account
3. **Navigate to:** Developer Console → Apps & Services
4. **Click:** "Add New App"
5. **Fill in all required fields:**
   - App name and description
   - OAuth configuration
   - Data usage details
   - Screenshots
   - Privacy policy
   - Support information

6. **Select APIs:**
   - Catalog Items API
   - Feeds API
   - Listings API
   - Inventory API
   - Orders API (if needed)
   - Reports API (if needed)

7. **Submit for Review**

#### Step 3: Amazon Review Process

- **Timeline:** Typically 2-4 weeks
- **Updates:** Amazon will email you
- **Common Issues:**
  - Missing privacy policy
  - Unclear data usage description
  - Incomplete screenshots
  - OAuth configuration errors

#### Step 4: Approval & Switching to LWA-Only

Once approved:

1. **Remove AWS credentials** from BT38 store config:

```json
{
  "refresh_token": "Atzr|...",
  "lwa_app_id": "amzn1.application-oa2-client...",
  "lwa_client_secret": "amzn1.oa2-cs...",
  "seller_id": "A1F83G8C2ARO7P",
  "marketplace_id": "A1F83G8C2ARO7P"
}
```

2. **Verify LWA-Only Mode** in logs:
```
✨ Initialized Amazon REST API client (LWA-ONLY MODE - Published app)
✨ Using LWA-only authentication (Published app mode)
✅ Successfully authenticated Amazon store: BT38
```

3. **Delete AWS IAM User** to stop any potential charges

✅ **You're now running in LWA-only mode!** No AWS charges ever.

---

## 🔄 Easy Mode Switching

The system automatically detects which mode to use:

- **AWS credentials present** → AWS Mode (Draft app)
- **No AWS credentials** → LWA-only Mode (Published app)

Just update the store's `api_key` JSON and restart!

---

## 📊 Cost Comparison

### AWS Mode (Temporary)
- AWS Free Tier: **$0** for 6 months
- After free tier: **~$1/month** for light usage
- Use while waiting for app approval

### LWA-Only Mode (Goal)
- **$0** forever
- No AWS charges
- After app publication

---

## 🆘 Troubleshooting

### "Unauthorized" Error with AWS Credentials

**Check:**
1. AWS credentials are correct
2. IAM policy has `execute-api:Invoke` permission
3. Credentials are properly formatted in JSON
4. Logs show "AWS MODE - Draft app"

### App Publication Rejected

**Common fixes:**
1. Add comprehensive privacy policy
2. Provide detailed data usage description
3. Include clear, high-quality screenshots
4. Verify OAuth redirect URIs match exactly
5. Add professional support email/website

### Mode Not Switching

**Solution:**
1. Update store's `api_key` JSON
2. Restart application
3. Check logs for mode confirmation
4. Trigger manual sync to test

---

## 📞 Support

- **AWS Issues:** AWS Support (if paid plan) or AWS Forums
- **Amazon SP-API:** Amazon Developer Support
- **App Issues:** Check logs in `/tmp/logs/` or contact system admin

---

## 🎯 Recommended Path

1. ✅ **Immediate:** Add AWS credentials (5 min) - Get Amazon sync working TODAY
2. 📝 **This Week:** Start app publication process (1 hour)
3. ⏳ **Wait:** 2-4 weeks for Amazon review
4. 🎉 **Switch:** Remove AWS credentials, use LWA-only mode
5. 💰 **Save:** No more AWS charges!

---

*Last Updated: November 2025*
