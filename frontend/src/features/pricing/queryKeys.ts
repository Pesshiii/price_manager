export const pricingKeys = {
  all: ['pricing'] as const,
  priceTypes: () => [...pricingKeys.all, 'price-types'] as const,
  priceType: (id: number) => [...pricingKeys.all, 'price-types', id] as const,
  rules: (supplierId?: number) => [...pricingKeys.all, 'rules', supplierId] as const,
  rule: (id: number) => [...pricingKeys.all, 'rules', 'detail', id] as const,
};
