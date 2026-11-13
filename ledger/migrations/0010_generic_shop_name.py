from django.db import migrations, models


OLD_SHOP_NAME = "SRI JAGADEESHWARI PROVISION STORES"
NEW_SHOP_NAME = "Credit Manager"


def remove_old_default_shop_name(apps, schema_editor):
    ShopProfile = apps.get_model("ledger", "ShopProfile")
    ShopProfile.objects.using(schema_editor.connection.alias).filter(
        shop_name__iexact=OLD_SHOP_NAME,
    ).update(shop_name=NEW_SHOP_NAME)


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0009_shopprofile_gstin_ownerprofile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="shopprofile",
            name="shop_name",
            field=models.CharField(default=NEW_SHOP_NAME, max_length=150),
        ),
        migrations.RunPython(
            remove_old_default_shop_name,
            migrations.RunPython.noop,
        ),
    ]
