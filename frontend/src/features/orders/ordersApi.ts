import { baseApi } from '../../shared/api/baseApi';
import type { Language } from '../../shared/i18n/languages';
import type {
  CancellationRequestCreate,
  CancellationRequestOut,
  OrderCreate,
  OrderCreated,
  OrderDetail,
  OrderList,
  QuoteIn,
  QuoteOut,
} from '../../shared/types/api';

// Checkout and orders (API_SPECIFICATION.md §6). The quote is informational;
// the order is created only by POST /orders with an Idempotency-Key; the
// customer's order screens refresh every 20 s (DEC-74).
export const ORDER_POLLING_MS = 20_000;

export const ordersApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getQuote: build.mutation<QuoteOut, { body: QuoteIn; language: Language }>({
      query: ({ body, language }) => ({
        url: 'checkout/quote',
        method: 'POST',
        body,
        params: { language },
      }),
    }),
    createOrder: build.mutation<OrderCreated, { body: OrderCreate; idempotencyKey: string }>({
      query: ({ body, idempotencyKey }) => ({
        url: 'orders',
        method: 'POST',
        body,
        headers: { 'Idempotency-Key': idempotencyKey },
      }),
      invalidatesTags: ['Orders', 'Cart', 'Addresses'],
    }),
    getOrders: build.query<OrderList, { page: number }>({
      query: ({ page }) => ({ url: 'orders', params: { page, page_size: 20 } }),
      providesTags: ['Orders'],
    }),
    getOrder: build.query<OrderDetail, string>({
      query: (id) => `orders/${id}`,
      providesTags: ['Orders'],
    }),
    requestCancellation: build.mutation<
      CancellationRequestOut,
      { orderId: string; body: CancellationRequestCreate }
    >({
      query: ({ orderId, body }) => ({
        url: `orders/${orderId}/cancellation-requests`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Orders'],
    }),
  }),
});

export const {
  useGetQuoteMutation,
  useCreateOrderMutation,
  useGetOrdersQuery,
  useGetOrderQuery,
  useRequestCancellationMutation,
} = ordersApi;
