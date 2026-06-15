export const pricingKeys = {
  all: ['pricing'] as const,
  priceTypes: () => [...pricingKeys.all, 'price-types'] as const,
};
