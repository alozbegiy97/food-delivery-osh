import { baseApi } from '../../shared/api/baseApi';
import type {
  CourierActiveList,
  CourierHistoryList,
  CourierHistoryOut,
  CourierMe,
  CourierOrderOut,
} from '../../shared/types/api';

// Stage 9 (API §10, DEC-151). The courier id comes from the session only;
// the backend checks the role and the ownership of every assignment.
// Courier screens refresh every 10 s (DEC-93).
export const COURIER_POLLING_MS = 10_000;

const TAGS = ['CourierOrders', 'AdminOrders', 'Couriers', 'Dashboard', 'Kitchen'] as const;

export const courierApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    courierMe: build.query<CourierMe, void>({
      query: () => 'courier/me',
      providesTags: ['CourierOrders'],
    }),
    setAvailability: build.mutation<CourierMe, boolean>({
      query: (isAvailable) => ({
        url: 'courier/me/availability',
        method: 'PATCH',
        body: { is_available: isAvailable },
      }),
      invalidatesTags: ['CourierOrders', 'Couriers'],
    }),
    courierOrders: build.query<CourierActiveList, void>({
      query: () => 'courier/orders',
      providesTags: ['CourierOrders'],
    }),
    courierHistory: build.query<CourierHistoryList, number>({
      query: (page) => ({ url: 'courier/orders', params: { history: true, page, page_size: 20 } }),
      providesTags: ['CourierOrders'],
    }),
    courierOrder: build.query<CourierOrderOut, string>({
      query: (id) => `courier/orders/${id}`,
      providesTags: ['CourierOrders'],
    }),
    acceptOrder: build.mutation<CourierOrderOut, string>({
      query: (id) => ({ url: `courier/orders/${id}/accept`, method: 'POST' }),
      invalidatesTags: [...TAGS],
    }),
    declineOrder: build.mutation<CourierHistoryOut, { id: string; reason: string | null }>({
      query: ({ id, reason }) => ({
        url: `courier/orders/${id}/decline`,
        method: 'POST',
        body: { reason },
      }),
      invalidatesTags: [...TAGS],
    }),
    pickUpOrder: build.mutation<CourierOrderOut, string>({
      query: (id) => ({ url: `courier/orders/${id}/picked-up`, method: 'POST' }),
      invalidatesTags: [...TAGS],
    }),
    deliverOrder: build.mutation<CourierHistoryOut, string>({
      query: (id) => ({ url: `courier/orders/${id}/delivered`, method: 'POST' }),
      invalidatesTags: [...TAGS],
    }),
  }),
});

export const {
  useCourierMeQuery,
  useSetAvailabilityMutation,
  useCourierOrdersQuery,
  useCourierHistoryQuery,
  useCourierOrderQuery,
  useAcceptOrderMutation,
  useDeclineOrderMutation,
  usePickUpOrderMutation,
  useDeliverOrderMutation,
} = courierApi;
