# Generated by Django 3.0.3 on 2020-03-12 21:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posapp', '0017_auto_20200312_1936'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='allows_fractions',
            field=models.BooleanField(default=True),
        ),
    ]
