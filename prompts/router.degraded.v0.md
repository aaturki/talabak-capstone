# router-degraded-v0

Intentional regression fixture for the deterministic local simulator only.
Classify every request as faq, even when it asks to track an order, return or
exchange a product, book a visit, or contact a human. Set order_id,
replacement_sku, slot_id, and reason to null. Preserve language ar/en from the
user's text. Set confidence to 0.98. Return the strict DomainRequest object.

This deliberately incorrect prompt is never the production router default.
Its exact header activates a transparent simulator fault for testing the
full-dataset regression gate. Results do not demonstrate a real LLM response
to prompt changes. The normal router remains router.v1.md.
