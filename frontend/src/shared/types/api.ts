// API types are generated from the backend OpenAPI contract with
// openapi-typescript (DEC-71): `npm run gen:api` writes ./openapi.ts.
// Do not edit openapi.ts by hand; aliases for frequently used schemas live here.
import type { components } from './openapi';

export type Schemas = components['schemas'];

export type HealthResponse = Schemas['HealthResponse'];
export type TokenResponse = Schemas['TokenResponse'];
export type MeResponse = Schemas['MeResponse'];
export type RegisterRequest = Schemas['RegisterRequest'];
export type LoginRequest = Schemas['LoginRequest'];
export type PasswordChangeRequest = Schemas['PasswordChangeRequest'];
export type PasswordForgotRequest = Schemas['PasswordForgotRequest'];
export type PasswordResetRequest = Schemas['PasswordResetRequest'];
export type AcceptedResponse = Schemas['AcceptedResponse'];
export type CredentialsRequest = Schemas['CredentialsRequest'];

// Telegram Mini App (MA-1, MA-2; API §2.3, §4)
export type WebAppAuthRequest = Schemas['WebAppAuthRequest'];
export type WebAppLinkRequest = Schemas['WebAppLinkRequest'];
export type ProfileUpdate = Schemas['ProfileUpdate'];

// Catalog and restaurant (stage 4A/4C)
export type CategoryOut = Schemas['CategoryOut'];
export type CategoryList = Schemas['CategoryList'];
export type ProductSummary = Schemas['ProductSummary'];
export type ProductList = Schemas['ProductList'];
export type ProductDetail = Schemas['ProductDetail'];
export type VariantOut = Schemas['VariantOut'];
export type ModifierGroupOut = Schemas['ModifierGroupOut'];
export type ModifierOut = Schemas['ModifierOut'];
export type RestaurantOut = Schemas['RestaurantOut'];
export type WorkingDayOut = Schemas['WorkingDayOut'];

// Catalog administration (stage 4B)
export type TranslationIn = Schemas['TranslationIn'];
export type TranslationOut = Schemas['TranslationOut'];
export type CategoryAdminOut = Schemas['CategoryAdminOut'];
export type CategoryAdminList = Schemas['CategoryAdminList'];
export type CategoryCreate = Schemas['CategoryCreate'];
export type CategoryUpdate = Schemas['CategoryUpdate'];
export type ProductAdminSummary = Schemas['ProductAdminSummary'];
export type ProductAdminList = Schemas['ProductAdminList'];
export type ProductAdminDetail = Schemas['ProductAdminDetail'];
export type ProductCreate = Schemas['ProductCreate'];
export type ProductUpdate = Schemas['ProductUpdate'];
export type VariantAdminOut = Schemas['VariantAdminOut'];
export type VariantCreate = Schemas['VariantCreate'];
export type VariantUpdate = Schemas['VariantUpdate'];
export type ModifierPriceIn = Schemas['ModifierPriceIn'];
export type ProductGroupLink = Schemas['ProductGroupLink'];
export type ModifierGroupAdminOut = Schemas['ModifierGroupAdminOut'];
export type ModifierGroupAdminList = Schemas['ModifierGroupAdminList'];
export type ModifierGroupCreate = Schemas['ModifierGroupCreate'];
export type ModifierGroupUpdate = Schemas['ModifierGroupUpdate'];
export type ModifierAdminOut = Schemas['ModifierAdminOut'];
export type ModifierCreate = Schemas['ModifierCreate'];
export type ModifierUpdate = Schemas['ModifierUpdate'];

// Server cart (stage 5)
export type CartOut = Schemas['CartOut'];
export type CartItemOut = Schemas['CartItemOut'];
export type CartIssueOut = Schemas['CartIssueOut'];
export type CartItemCreate = Schemas['CartItemCreate'];
export type CartItemUpdate = Schemas['CartItemUpdate'];

// Checkout and orders (stage 6)
export type AddressOut = Schemas['AddressOut'];
export type AddressList = Schemas['AddressList'];
export type AddressCreate = Schemas['AddressCreate'];
export type AddressUpdate = Schemas['AddressUpdate'];
export type DeliveryAddressIn = Schemas['DeliveryAddressIn'];
export type QuoteIn = Schemas['QuoteIn'];
export type QuoteOut = Schemas['QuoteOut'];
export type ProblemOut = Schemas['ProblemOut'];
export type OrderCreate = Schemas['OrderCreate'];
export type OrderCreated = Schemas['OrderCreated'];
export type OrderList = Schemas['OrderList'];
export type OrderSummary = Schemas['OrderSummary'];
export type OrderDetail = Schemas['OrderDetail'];
export type OrderItemOut = Schemas['OrderItemOut'];
export type StatusHistoryOut = Schemas['StatusHistoryOut'];
export type CancellationRequestOut = Schemas['CancellationRequestOut'];
export type CancellationRequestCreate = Schemas['CancellationRequestCreate'];

// Payments (stage 7)
export type PaymentMethodOut = Schemas['PaymentMethodOut'];
export type PaymentMethodList = Schemas['PaymentMethodList'];
export type MockConfirmIn = Schemas['MockConfirmIn'];
export type MockConfirmOut = Schemas['MockConfirmOut'];
export type PaymentOut = Schemas['PaymentOut'];

// Administration and kitchen (stage 8)
export type AdminOrderList = Schemas['AdminOrderList'];
export type AdminOrderSummary = Schemas['AdminOrderSummary'];
export type AdminOrderDetail = Schemas['AdminOrderDetail'];
export type AdminHistoryOut = Schemas['AdminHistoryOut'];
export type StatusChange = Schemas['StatusChange'];
export type AdminRequestList = Schemas['AdminRequestList'];
export type AdminRequestOut = Schemas['AdminRequestOut'];
export type StaffList = Schemas['StaffList'];
export type StaffOut = Schemas['StaffOut'];
export type StaffCreate = Schemas['StaffCreate'];
export type SettingsOut = Schemas['SettingsOut'];
export type SettingsUpdate = Schemas['SettingsUpdate'];
export type WeekHours = Schemas['WeekHours'];
export type DayHoursIn = Schemas['DayHoursIn'];
export type ZoneList = Schemas['AdminZoneList'];
export type ZoneOut = Schemas['AdminZoneOut'];
export type ZoneCreate = Schemas['ZoneCreate'];
export type ZoneUpdate = Schemas['ZoneUpdate'];
export type SummaryOut = Schemas['SummaryOut'];
export type ChartOut = Schemas['ChartOut'];
export type TopProductsOut = Schemas['TopProductsOut'];
export type KitchenQueue = Schemas['KitchenQueue'];
export type KitchenOrderOut = Schemas['KitchenOrderOut'];

// Stage 9: couriers and assignments (API §9 "Couriers", §10; DEC-151).
export type CourierOut = Schemas['CourierOut'];
export type CourierList = Schemas['CourierList'];
export type CourierSettingsIn = Schemas['CourierSettingsIn'];
export type AssignmentOut = Schemas['AssignmentOut'];
export type CourierMe = Schemas['CourierMe'];
export type CourierOrderOut = Schemas['CourierOrderOut'];
export type CourierActiveList = Schemas['CourierActiveList'];
export type CourierHistoryOut = Schemas['CourierHistoryOut'];
export type CourierHistoryList = Schemas['CourierHistoryList'];

// The unified error body (DEC-73, DEC-103) is produced by exception handlers
// and is therefore not part of the generated schemas.
export interface ApiFieldError {
  field: string;
  message: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown;
    request_id: string;
  };
}
