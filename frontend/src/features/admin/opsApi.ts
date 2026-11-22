import { baseApi } from '../../shared/api/baseApi';
import type {
  AdminOrderDetail,
  AdminOrderList,
  AdminRequestList,
  AdminRequestOut,
  ChartOut,
  CourierList,
  CourierOut,
  CourierSettingsIn,
  DayHoursIn,
  KitchenOrderOut,
  KitchenQueue,
  SettingsOut,
  SettingsUpdate,
  StaffCreate,
  StaffList,
  StaffOut,
  StatusChange,
  SummaryOut,
  TopProductsOut,
  WeekHours,
  ZoneCreate,
  ZoneList,
  ZoneOut,
  ZoneUpdate,
} from '../../shared/types/api';

// Stage 8 (API §9, DEC-150). The backend checks every role; the interface
// only hides what a role cannot use. Staff screens refresh every 10 s (DEC-93).
export const STAFF_POLLING_MS = 10_000;

export interface PeriodArgs {
  dateFrom?: string;
  dateTo?: string;
}

export interface AdminOrdersArgs {
  status?: string;
  deliveryType?: string;
  dateFrom?: string;
  dateTo?: string;
  number?: string;
  awaitingPayment: boolean;
  page: number;
}

const period = ({ dateFrom, dateTo }: PeriodArgs) => ({
  ...(dateFrom ? { date_from: dateFrom } : {}),
  ...(dateTo ? { date_to: dateTo } : {}),
});

const ORDER_TAGS = ['AdminOrders', 'Kitchen', 'Dashboard', 'Orders', 'Couriers'] as const;

export const opsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    // Dashboard
    dashboardSummary: build.query<SummaryOut, PeriodArgs>({
      query: (args) => ({ url: 'admin/dashboard/summary', params: period(args) }),
      providesTags: ['Dashboard'],
    }),
    dashboardChart: build.query<ChartOut, PeriodArgs>({
      query: (args) => ({ url: 'admin/dashboard/orders-chart', params: period(args) }),
      providesTags: ['Dashboard'],
    }),
    dashboardTop: build.query<TopProductsOut, PeriodArgs>({
      query: (args) => ({ url: 'admin/dashboard/top-products', params: period(args) }),
      providesTags: ['Dashboard'],
    }),

    // Orders and cancellation requests
    adminOrders: build.query<AdminOrderList, AdminOrdersArgs>({
      query: ({ status, deliveryType, dateFrom, dateTo, number, awaitingPayment, page }) => ({
        url: 'admin/orders',
        params: {
          page,
          page_size: 20,
          awaiting_payment: awaitingPayment,
          ...(status ? { status } : {}),
          ...(deliveryType ? { delivery_type: deliveryType } : {}),
          ...(number ? { number } : {}),
          ...period({ dateFrom, dateTo }),
        },
      }),
      providesTags: ['AdminOrders'],
    }),
    adminOrder: build.query<AdminOrderDetail, string>({
      query: (id) => `admin/orders/${id}`,
      providesTags: ['AdminOrders'],
    }),
    changeOrderStatus: build.mutation<AdminOrderDetail, { id: string; body: StatusChange }>({
      query: ({ id, body }) => ({ url: `admin/orders/${id}/status`, method: 'PATCH', body }),
      invalidatesTags: [...ORDER_TAGS],
    }),
    cancellationRequests: build.query<AdminRequestList, { status: string; page: number }>({
      query: ({ status, page }) => ({
        url: 'admin/cancellation-requests',
        params: { status, page, page_size: 20 },
      }),
      providesTags: ['AdminOrders'],
    }),
    approveRequest: build.mutation<AdminRequestOut, string>({
      query: (id) => ({ url: `admin/cancellation-requests/${id}/approve`, method: 'POST' }),
      invalidatesTags: [...ORDER_TAGS],
    }),
    rejectRequest: build.mutation<AdminRequestOut, { id: string; adminComment: string }>({
      query: ({ id, adminComment }) => ({
        url: `admin/cancellation-requests/${id}/reject`,
        method: 'POST',
        body: { admin_comment: adminComment },
      }),
      invalidatesTags: [...ORDER_TAGS],
    }),

    // Courier assignment (DEC-48…DEC-51, DEC-151)
    assignCourier: build.mutation<AdminOrderDetail, { id: string; courierId: string }>({
      query: ({ id, courierId }) => ({
        url: `admin/orders/${id}/assign-courier`,
        method: 'POST',
        body: { courier_id: courierId },
      }),
      invalidatesTags: ['AdminOrders', 'Couriers', 'Dashboard'],
    }),
    autoAssignCourier: build.mutation<AdminOrderDetail, string>({
      query: (id) => ({ url: `admin/orders/${id}/auto-assign-courier`, method: 'POST' }),
      invalidatesTags: ['AdminOrders', 'Couriers', 'Dashboard'],
    }),
    couriers: build.query<CourierList, void>({
      query: () => 'admin/couriers',
      providesTags: ['Couriers'],
    }),
    updateCourier: build.mutation<CourierOut, { id: string; body: CourierSettingsIn }>({
      query: ({ id, body }) => ({
        url: `admin/couriers/${id}/availability`,
        method: 'PATCH',
        body,
      }),
      invalidatesTags: ['Couriers'],
    }),

    // Kitchen (cook and admin)
    kitchenQueue: build.query<KitchenQueue, void>({
      query: () => 'staff/kitchen/orders',
      providesTags: ['Kitchen'],
    }),
    kitchenAction: build.mutation<KitchenOrderOut, { id: string; action: 'start' | 'ready' }>({
      query: ({ id, action }) => ({ url: `staff/kitchen/orders/${id}/${action}`, method: 'POST' }),
      invalidatesTags: [...ORDER_TAGS],
    }),

    // Staff (DEC-150)
    staff: build.query<StaffList, void>({
      query: () => ({ url: 'admin/staff', params: { page_size: 100 } }),
      providesTags: ['Staff'],
    }),
    createStaff: build.mutation<StaffOut, StaffCreate>({
      query: (body) => ({ url: 'admin/staff', method: 'POST', body }),
      invalidatesTags: ['Staff', 'Couriers'],
    }),
    updateStaffRoles: build.mutation<StaffOut, { id: string; roles: ('cook' | 'courier')[] }>({
      query: ({ id, roles }) => ({
        url: `admin/staff/${id}/roles`,
        method: 'PATCH',
        body: { roles },
      }),
      invalidatesTags: ['Staff', 'Couriers'],
    }),
    setStaffActive: build.mutation<StaffOut, { id: string; active: boolean }>({
      query: ({ id, active }) => ({
        url: `admin/staff/${id}/${active ? 'reactivate' : 'deactivate'}`,
        method: 'POST',
      }),
      invalidatesTags: ['Staff', 'Couriers'],
    }),

    // Settings and working hours
    adminSettings: build.query<SettingsOut, void>({
      query: () => 'admin/settings',
      providesTags: ['Settings'],
    }),
    updateSettings: build.mutation<SettingsOut, SettingsUpdate>({
      query: (body) => ({ url: 'admin/settings', method: 'PATCH', body }),
      invalidatesTags: ['Settings'],
    }),
    workingHours: build.query<WeekHours, void>({
      query: () => 'admin/working-hours',
      providesTags: ['Settings'],
    }),
    saveWorkingHours: build.mutation<WeekHours, DayHoursIn[]>({
      query: (items) => ({ url: 'admin/working-hours', method: 'PUT', body: { items } }),
      invalidatesTags: ['Settings'],
    }),

    // Delivery zones
    zones: build.query<ZoneList, void>({
      query: () => 'admin/delivery-zones',
      providesTags: ['Zones'],
    }),
    createZone: build.mutation<ZoneOut, ZoneCreate>({
      query: (body) => ({ url: 'admin/delivery-zones', method: 'POST', body }),
      invalidatesTags: ['Zones'],
    }),
    updateZone: build.mutation<ZoneOut, { id: string; body: ZoneUpdate }>({
      query: ({ id, body }) => ({ url: `admin/delivery-zones/${id}`, method: 'PATCH', body }),
      invalidatesTags: ['Zones'],
    }),
    deactivateZone: build.mutation<ZoneOut, string>({
      query: (id) => ({ url: `admin/delivery-zones/${id}`, method: 'DELETE' }),
      invalidatesTags: ['Zones'],
    }),
  }),
});

export const {
  useDashboardSummaryQuery,
  useDashboardChartQuery,
  useDashboardTopQuery,
  useAdminOrdersQuery,
  useAdminOrderQuery,
  useChangeOrderStatusMutation,
  useCancellationRequestsQuery,
  useApproveRequestMutation,
  useRejectRequestMutation,
  useKitchenQueueQuery,
  useKitchenActionMutation,
  useStaffQuery,
  useCreateStaffMutation,
  useUpdateStaffRolesMutation,
  useSetStaffActiveMutation,
  useAdminSettingsQuery,
  useUpdateSettingsMutation,
  useWorkingHoursQuery,
  useSaveWorkingHoursMutation,
  useZonesQuery,
  useCreateZoneMutation,
  useUpdateZoneMutation,
  useDeactivateZoneMutation,
  useAssignCourierMutation,
  useAutoAssignCourierMutation,
  useCouriersQuery,
  useUpdateCourierMutation,
} = opsApi;
