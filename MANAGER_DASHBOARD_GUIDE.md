# 🎯 Manager Dashboard Guide

## Correct URL

**Access the manager dashboard at:**
```
http://127.0.0.1:8000/admin-dashboard/
```

⚠️ **Note:** The URL uses **hyphens** (`admin-dashboard`), not underscores. URLs with underscores (`admin_dashboard`) will result in a 404 error.

---

## Getting Started

### Prerequisites
- You must be a **staff member** to access this dashboard
- Django admin user account with `is_staff=True`

### Quick Access
1. Go to Django admin: `http://127.0.0.1:8000/admin/`
2. Create a staff user if you don't have one
3. Visit the manager dashboard at `/admin-dashboard/`

---

## Dashboard Features

### 📊 Key Metrics Summary
- **Total Users** - All registered members
- **Active Users** - Currently active members matching filters
- **Staff Members** - Accounts with admin access
- **Inactive Users** - Deactivated accounts
- **Users Without Habits** - New users needing onboarding
- **Donors** - Users who have supported the platform

### 🔍 Search & Filter
- **Search** - Find users by:
  - Username
  - Email address
  - Full name
  - Phone number
  - Bitcoin wallet address
  
- **Filters**:
  - Account Type (All, Staff, Members, Inactive)
  - Activity Level (All, With habits, Without habits, Donors, Never logged in)

### 📋 User Directory
Comprehensive table showing:
- User profile and status
- Theme and font preferences
- Color scheme information
- Personal details (gender, age, contact info)
- Habit activity (active habits, entries, reviews)
- Payment information (M-Pesa, Bitcoin saved)
- Quick action buttons to manage individual users

### ⚡ System Snapshot
Real-time platform health metrics:
- Total habits being tracked
- Entries recorded today
- Weekly reviews completed
- Total completed donations

### 🆕 Recent Signups
Overview of newest members with:
- Username and full name
- Registration date
- Number of habits created

### 🔗 Quick Actions
Fast shortcuts to Django admin areas:
- Manage All Users
- User Profiles
- All Habits
- Habit Entries
- Weekly Reviews
- All Donations

### 💰 Payment Insights
- Donation breakdown by payment method
- Interactive doughnut chart
- Transaction count and totals
- Payment method summary

### 🏆 Top Active Members
Ranked table showing most engaged users by:
- Number of habits
- Entries logged
- Weekly reviews
- Donations made

### 📊 Transaction History
Recent donation activity showing:
- Payment method (M-Pesa, Bitcoin, Lightning)
- Amount and currency
- Transaction status
- Timestamp

---

## Common Tasks

### Find a User
1. Enter username, email, or phone in the search box
2. Click "Search"
3. Click user's "User record" button to edit in Django admin

### Filter by Status
1. Select "Account Type" filter (Staff/Members/Inactive)
2. Click "Search"
3. Refine results with Activity filter

### View User Donations
1. Find user in directory
2. Click "Donations" button in the Actions column
3. View all donations for that user in Django admin

### Review Platform Activity
- Check "System Snapshot" for today's entries and reviews
- View "Top Active Members" for engagement rankings
- Check "Recent Donations" for payment activity

### Manage Staff Access
1. Click "Manage Users" button
2. Find user in Django admin
3. Check "Staff status" to grant/revoke admin access

---

## Key Buttons

| Button | Purpose |
|--------|---------|
| Search | Apply filters and search |
| Clear all | Reset all filters |
| Django Admin | Full admin interface |
| Manage Users | User management in Django admin |
| User record | Edit specific user profile |
| Profile record | Edit user settings & preferences |
| Habits | View user's habits |
| Donations | View user's donations |

---

## Tips & Best Practices

✅ **Do:**
- Use filters to find specific user segments
- Check the System Snapshot daily for platform health
- Review Top Active Members to identify loyal users
- Monitor Recent Donations for payment issues

❌ **Don't:**
- Manually edit financial data - use Django admin for proper records
- Disable active users without backup communication
- Forget to assign staff roles when needed

---

## Troubleshooting

### Dashboard Not Loading?
- Confirm you're a staff member
- Check URL is exactly `/admin-dashboard/` (with hyphens)
- Clear browser cache and reload

### No Users Showing?
- Check "Account Type" filter isn't set to "Staff only"
- Try clearing all filters with "Clear all" button
- Verify users exist in Django admin

### Can't Access Django Admin Links?
- Ensure you have superuser or staff status
- Check permissions in Django admin user page

---

## Related Documentation
- Django Admin: `/admin/`
- Main App: `/`
- Donate Page: `/donate/`
- User Profile: `/profile/`
