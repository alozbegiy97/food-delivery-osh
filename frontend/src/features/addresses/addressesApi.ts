import { baseApi } from '../../shared/api/baseApi';
import type { AddressCreate, AddressList, AddressOut, AddressUpdate } from '../../shared/types/api';

// Address book of the customer (API_SPECIFICATION.md §4, DEC-148). The
// checkout lets the customer pick a saved address or add a new one.
export const addressesApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getAddresses: build.query<AddressList, void>({
      query: () => ({ url: 'users/me/addresses', params: { page_size: 100 } }),
      providesTags: ['Addresses'],
    }),
    createAddress: build.mutation<AddressOut, AddressCreate>({
      query: (body) => ({ url: 'users/me/addresses', method: 'POST', body }),
      invalidatesTags: ['Addresses'],
    }),
    updateAddress: build.mutation<AddressOut, { id: string; body: AddressUpdate }>({
      query: ({ id, body }) => ({ url: `users/me/addresses/${id}`, method: 'PATCH', body }),
      invalidatesTags: ['Addresses'],
    }),
    deleteAddress: build.mutation<void, string>({
      query: (id) => ({ url: `users/me/addresses/${id}`, method: 'DELETE' }),
      invalidatesTags: ['Addresses'],
    }),
    setDefaultAddress: build.mutation<AddressOut, string>({
      query: (id) => ({ url: `users/me/addresses/${id}/default`, method: 'POST' }),
      invalidatesTags: ['Addresses'],
    }),
  }),
});

export const {
  useGetAddressesQuery,
  useCreateAddressMutation,
  useUpdateAddressMutation,
  useDeleteAddressMutation,
  useSetDefaultAddressMutation,
} = addressesApi;
