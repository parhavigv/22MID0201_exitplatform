# IT Clearance Procedure

**Version:** 1.4
**Effective From:** 2025-01-01
**Owner:** IT Department / Human Resources

---

## 1. Purpose

This procedure defines the steps required to revoke an exiting employee's access to all company systems, collect company-owned devices, and certify IT clearance before the full-and-final settlement is released.

---

## 2. Scope

Applies to all employees, contractors, and interns exiting the organisation, regardless of exit type (resignation, termination, contract end, retirement).

---

## 3. IT Clearance Timeline

IT clearance must be completed **on or before the last working day**. If clearance is not complete, the relieving letter will not be issued and the F&F settlement will be held until clearance is confirmed.

| Action | Responsible Party | Deadline |
|---|---|---|
| IT Clearance Task opened in exit system | HR (automatic, on resignation) | Day 1 of notice |
| Device audit list shared with employee | IT | Within 3 business days of resignation |
| Accounts deactivation scheduled | IT | 24 hours before last working day |
| Device return confirmed | IT / Admin | On last working day |
| IT Clearance certificate issued | IT | Within 2 business days of last working day |

---

## 4. System Access Deactivation

IT will deactivate the following on the last working day, in the order listed:

1. **Active Directory / Azure AD account** — disables login to all SSO-connected applications simultaneously.
2. **Email account** — set to out-of-office auto-reply, then archived. No new mail is delivered after deactivation. The archive is retained for 90 days per the data-retention policy.
3. **VPN access** — revoked at the same time as the AD account.
4. **Cloud platform access** (AWS, GCP, Azure) — all IAM roles and service accounts associated with the employee are removed.
5. **Code repository access** (GitHub, GitLab, Bitbucket) — removed from all teams and organisations.
6. **SaaS application accounts** — Jira, Confluence, Salesforce, HubSpot, Slack, and all other tools provisioned by IT. Employee is removed from all channels and workspaces.
7. **Privileged/admin accounts** — deactivated 48 hours before the last working day for employees with elevated access, after KT is confirmed complete.

---

## 5. Accounts the Employee Must Close Themselves

The following must be closed by the employee and confirmed to IT:

- Personal accounts linked to company email (e.g., trial SaaS tools signed up with the work email).
- Any API keys or personal access tokens created for automation that were not registered with IT.
- SSH keys added to servers outside the standard provisioning process.

The employee must sign a declaration confirming these have been removed. Failure to do so may be treated as a breach of the NDA.

---

## 6. Device Return

### 6.1 Items to Return

The following must be returned on or before the last working day:

- Laptops, desktops, tablets — all company-issued computing devices.
- Mobile phones provisioned by the company.
- Access cards, door badges, and biometric tokens.
- Security keys (YubiKeys, RSA tokens, etc.).
- Any peripherals (monitors, keyboards, docking stations) issued by IT.

### 6.2 Condition of Devices

Devices must be returned in good working condition. Normal wear and tear is acceptable. Damage beyond normal wear (cracked screens, liquid damage, missing components) will be assessed by IT and charged to the employee's F&F settlement at current market replacement cost.

### 6.3 Data Wiping

IT will wipe all returned devices before reissuing them. The employee must ensure no personal data remains on company devices before return. The company is not responsible for recovering personal data after wiping.

### 6.4 Remote Employees

Employees working remotely must ship devices to the registered company address via a trackable courier at company expense (pre-paid label provided by Admin). Devices must be dispatched within 2 business days of the last working day. IT clearance is issued once devices are received and inspected.

---

## 7. Employees With Elevated Access

Employees with admin, DBA, or privileged access are subject to additional steps:

- A privileged-access inventory is produced at least 15 days before the last working day.
- Credentials for all shared/service accounts are rotated before the last working day.
- IT and the Security team must sign off on privileged access clearance separately from standard IT clearance.
- The relieving letter is blocked until privileged-access clearance is confirmed.

---

## 8. IT Clearance Certificate

Once all steps above are complete, IT issues a signed IT Clearance Certificate referencing the employee's name, employee code, and last working day. This certificate is uploaded to the exit system and triggers the F&F settlement calculation.

Without this certificate, Finance cannot process the final salary payment or issue Form 16 for the year.

---

## 9. Exceptions

If a device is lost or stolen before return, the employee must file a police FIR and submit a copy to IT within 3 days of discovery. The market replacement value will be deducted from F&F unless insurance covers the loss.

Exceptions to any step in this procedure require written approval from the IT Head and HR Head.
