def checkout(subtotal: float, discount_pct: float, tax_pct: float) -> float:
    """Return final total. BUG: tax is currently calculated before the discount."""
    taxed = subtotal * (1 + tax_pct / 100)
    discounted = taxed * (1 - discount_pct / 100)
    return round(discounted, 2)
