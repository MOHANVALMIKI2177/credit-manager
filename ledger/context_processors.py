from .models import ShopProfile


def shop_profile(_request):
    return {"shop_profile": ShopProfile.objects.first()}
