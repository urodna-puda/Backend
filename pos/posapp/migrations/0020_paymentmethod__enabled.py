# Generated by Django 3.0.4 on 2020-04-18 21:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posapp', '0019_auto_20200321_1648_squashed_0024_auto_20200417_1036'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentmethod',
            name='_enabled',
            field=models.BooleanField(db_column='enabled', default=False),
        ),
    ]