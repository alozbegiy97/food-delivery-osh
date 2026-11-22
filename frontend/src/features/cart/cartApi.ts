import { baseApi } from '../../shared/api/baseApi';
import type { Language } from '../../shared/i18n/languages';
import type { CartItemCreate, CartItemUpdate, CartOut } from '../../shared/types/api';

// Server cart (API_SPECIFICATION.md §5). Every price, total and the
// availability of each line come from the backend (DEC-08); the client only
// sends the selection, the quantity and the instructions. After a change the
// cart is fetched again in the current language.
export const cartApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getCart: build.query<CartOut, Language>({
      query: (language) => ({ url: 'cart', params: { language } }),
      providesTags: ['Cart'],
    }),
    addCartItem: build.mutation<CartOut, CartItemCreate>({
      query: (body) => ({ url: 'cart/items', method: 'POST', body }),
      invalidatesTags: ['Cart'],
    }),
    updateCartItem: build.mutation<CartOut, { id: string; body: CartItemUpdate }>({
      query: ({ id, body }) => ({ url: `cart/items/${id}`, method: 'PATCH', body }),
      invalidatesTags: ['Cart'],
    }),
    deleteCartItem: build.mutation<void, string>({
      query: (id) => ({ url: `cart/items/${id}`, method: 'DELETE' }),
      invalidatesTags: ['Cart'],
    }),
    clearCart: build.mutation<void, void>({
      query: () => ({ url: 'cart', method: 'DELETE' }),
      invalidatesTags: ['Cart'],
    }),
  }),
});

export const {
  useGetCartQuery,
  useAddCartItemMutation,
  useUpdateCartItemMutation,
  useDeleteCartItemMutation,
  useClearCartMutation,
} = cartApi;

/** Limits of DEC-146 (also returned by the API in every cart response). */
export const MAX_LINE_QUANTITY = 99;
export const MAX_INSTRUCTIONS_LENGTH = 500;
