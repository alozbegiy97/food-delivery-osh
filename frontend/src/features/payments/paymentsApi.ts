import { baseApi } from '../../shared/api/baseApi';
import type { MockConfirmIn, MockConfirmOut, PaymentMethodList } from '../../shared/types/api';

// Payments (API_SPECIFICATION.md §7, DEC-149). Only a simulated card payment:
// the request carries the order, the attempt and the chosen outcome — never
// card data. Every confirmation refreshes the order (attempts, status).
export const paymentsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getPaymentMethods: build.query<PaymentMethodList, void>({
      query: () => 'payment-methods',
    }),
    confirmMockPayment: build.mutation<MockConfirmOut, MockConfirmIn>({
      query: (body) => ({ url: 'payments/mock/confirm', method: 'POST', body }),
      invalidatesTags: ['Orders'],
    }),
  }),
});

export const { useGetPaymentMethodsQuery, useConfirmMockPaymentMutation } = paymentsApi;
