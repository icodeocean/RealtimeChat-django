# Generated by Django 2.2.15 on 2020-08-25 18:02

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('notification', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='notification',
            name='action_object',
        ),
    ]
