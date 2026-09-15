from talabak.domain import Store,Session


def test_catalog_answer_contains_requested_product_facts_and_updates_with_stock():
    store=Store()
    try:
        first=store.lookup_catalog(Session(),"ما سعر SKU-H100؟")
        assert '200 ر.س' in first['message'] and 'المخزون المتاح 8' in first['message']
        assert 'SKU-H200' not in first['message']
        with store.db:
            store.db.execute("UPDATE products SET stock=0 WHERE sku='SKU-H100'")
        result=store.lookup_catalog(Session(language='en'),"What is the price and stock of SKU-H100?")
        assert 'SAR 200' in result['message'] and 'available stock 0' in result['message']
        assert 'catalog-v1' in result['sources']
    finally:
        store.close()


def test_catalog_unknown_sku_does_not_substitute_another_product():
    store=Store()
    try:
        result=store.lookup_catalog(Session(language='en'),"Price of SKU-NOTFOUND?")
        assert 'not found' in result['message'] and 'SAR 200' not in result['message']
    finally:
        store.close()
