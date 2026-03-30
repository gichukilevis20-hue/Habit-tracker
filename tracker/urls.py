from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path('contact/', views.contact_us, name='contact_us'),
    path('', views.home, name='home'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/users/', views.admin_users, name='admin_users'),
    path('admin-dashboard/users/create/', views.admin_user_create, name='admin_user_create'),
    path('admin-dashboard/users/<int:user_id>/edit/', views.admin_user_edit, name='admin_user_edit'),
    path('admin-dashboard/users/<int:user_id>/delete/', views.admin_user_delete, name='admin_user_delete'),
    path('admin-dashboard/habits/', views.admin_habits, name='admin_habits'),
    path('admin-dashboard/habits/create/', views.admin_habit_create, name='admin_habit_create'),
    path('admin-dashboard/habits/<int:habit_id>/edit/', views.admin_habit_edit, name='admin_habit_edit'),
    path('admin-dashboard/habits/<int:habit_id>/delete/', views.admin_habit_delete, name='admin_habit_delete'),
    path('admin-dashboard/donations/', views.admin_donations, name='admin_donations'),
    path('admin-dashboard/donations/create/', views.admin_donation_create, name='admin_donation_create'),
    path('admin-dashboard/donations/<int:donation_id>/edit/', views.admin_donation_edit, name='admin_donation_edit'),
    path('admin-dashboard/donations/<int:donation_id>/delete/', views.admin_donation_delete, name='admin_donation_delete'),
    path('admin-dashboard/messages/', views.admin_messages, name='admin_messages'),
    path('admin-dashboard/messages/<int:message_id>/', views.admin_message_detail, name='admin_message_detail'),
    path('admin-dashboard/messages/create/', views.admin_message_create, name='admin_message_create'),
    path('admin-dashboard/messages/<int:message_id>/edit/', views.admin_message_edit, name='admin_message_edit'),
    path('admin-dashboard/messages/<int:message_id>/delete/', views.admin_message_delete, name='admin_message_delete'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', auth_views.LoginView.as_view(template_name='tracker/login.html', authentication_form=LoginForm), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('habit/create/', views.create_habit, name='create_habit'),
    path('habit/<int:habit_id>/edit/', views.edit_habit, name='edit_habit'),
    path('habit/<int:habit_id>/delete/', views.delete_habit, name='delete_habit'),
    path('habit/<int:habit_id>/entry/', views.habit_entry, name='habit_entry'),
    path('habit/<int:habit_id>/review/', views.weekly_review, name='weekly_review'),
    path('calendar/events/', views.calendar_events, name='calendar_events'),
    path('calendar/<slug:date_str>/', views.calendar_day, name='calendar_day'),
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    path('donate/', views.donate, name='donate'),
    path('export/', views.export_data, name='export_data'),
    path('privacy/', views.privacy_policy, name='privacy_policy'),
]
