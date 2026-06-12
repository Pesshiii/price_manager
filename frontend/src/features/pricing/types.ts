export interface PriceType {
  id: number;
  name: string;
  label: string;
}

export interface PriceTypeWritePayload {
  name: string;
  label: string;
}

export type PricingRuleMode = 'fixed' | 'formula';

export interface PricingRule {
  id: number;
  supplier: number;
  source_price_type: number;
  dest_price_type: number;
  mode: PricingRuleMode;
  params: Record<string, unknown>;
  priority: number;
  category: number | null;
  price_from: string | null;
  price_to: string | null;
  date_from: string | null;
  date_to: string | null;
}

export interface PricingRuleWritePayload {
  supplier: number;
  source_price_type: number;
  dest_price_type: number;
  mode: PricingRuleMode;
  params: Record<string, unknown>;
  priority: number;
  category?: number | null;
  price_from?: string | null;
  price_to?: string | null;
  date_from?: string | null;
  date_to?: string | null;
}
