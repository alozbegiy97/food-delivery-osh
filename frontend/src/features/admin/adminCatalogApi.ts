import { baseApi } from '../../shared/api/baseApi';
import type {
  CategoryAdminList,
  CategoryAdminOut,
  CategoryCreate,
  CategoryUpdate,
  ModifierAdminOut,
  ModifierCreate,
  ModifierGroupAdminList,
  ModifierGroupAdminOut,
  ModifierGroupCreate,
  ModifierGroupUpdate,
  ModifierPriceIn,
  ModifierUpdate,
  ProductAdminDetail,
  ProductAdminList,
  ProductCreate,
  ProductGroupLink,
  ProductUpdate,
  VariantCreate,
  VariantUpdate,
} from '../../shared/types/api';

// Catalog administration (API_SPECIFICATION.md §9 "Catalog"). Every change
// also invalidates the public catalog cache ('Catalog') so the site shows it.
// Admin lists refresh by polling every 10 s (DEC-93).
export const ADMIN_POLLING_MS = 10_000;

export interface AdminProductsArgs {
  categoryId?: string;
  search?: string;
  status: 'active' | 'deleted' | 'all';
}

const CATEGORY_TAGS = ['AdminCategories', 'Catalog'] as const;
const PRODUCT_TAGS = ['AdminProducts', 'AdminCategories', 'Catalog'] as const;
const GROUP_TAGS = ['AdminGroups', 'AdminProducts', 'Catalog'] as const;

export const adminCatalogApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    // Categories
    adminCategories: build.query<CategoryAdminList, void>({
      query: () => 'admin/categories',
      providesTags: ['AdminCategories'],
    }),
    createCategory: build.mutation<CategoryAdminOut, CategoryCreate>({
      query: (body) => ({ url: 'admin/categories', method: 'POST', body }),
      invalidatesTags: [...CATEGORY_TAGS],
    }),
    updateCategory: build.mutation<CategoryAdminOut, { id: string; body: CategoryUpdate }>({
      query: ({ id, body }) => ({ url: `admin/categories/${id}`, method: 'PATCH', body }),
      invalidatesTags: [...CATEGORY_TAGS],
    }),
    deactivateCategory: build.mutation<void, string>({
      query: (id) => ({ url: `admin/categories/${id}`, method: 'DELETE' }),
      invalidatesTags: [...CATEGORY_TAGS],
    }),
    uploadCategoryImage: build.mutation<CategoryAdminOut, { id: string; file: File }>({
      query: ({ id, file }) => {
        const body = new FormData();
        body.append('file', file);
        return { url: `admin/categories/${id}/image`, method: 'POST', body };
      },
      invalidatesTags: [...CATEGORY_TAGS],
    }),

    // Products
    adminProducts: build.query<ProductAdminList, AdminProductsArgs>({
      query: ({ categoryId, search, status }) => ({
        url: 'admin/products',
        params: {
          status,
          page_size: 100,
          ...(categoryId ? { category_id: categoryId } : {}),
          ...(search ? { search } : {}),
        },
      }),
      providesTags: ['AdminProducts'],
    }),
    adminProduct: build.query<ProductAdminDetail, string>({
      query: (id) => `admin/products/${id}`,
      providesTags: ['AdminProducts'],
    }),
    createProduct: build.mutation<ProductAdminDetail, ProductCreate>({
      query: (body) => ({ url: 'admin/products', method: 'POST', body }),
      invalidatesTags: [...PRODUCT_TAGS],
    }),
    updateProduct: build.mutation<ProductAdminDetail, { id: string; body: ProductUpdate }>({
      query: ({ id, body }) => ({ url: `admin/products/${id}`, method: 'PATCH', body }),
      invalidatesTags: [...PRODUCT_TAGS],
    }),
    deleteProduct: build.mutation<void, string>({
      query: (id) => ({ url: `admin/products/${id}`, method: 'DELETE' }),
      invalidatesTags: [...PRODUCT_TAGS],
    }),
    addVariant: build.mutation<ProductAdminDetail, { productId: string; body: VariantCreate }>({
      query: ({ productId, body }) => ({
        url: `admin/products/${productId}/variants`,
        method: 'POST',
        body,
      }),
      invalidatesTags: [...PRODUCT_TAGS],
    }),
    updateVariant: build.mutation<ProductAdminDetail, { id: string; body: VariantUpdate }>({
      query: ({ id, body }) => ({ url: `admin/variants/${id}`, method: 'PATCH', body }),
      invalidatesTags: [...PRODUCT_TAGS],
    }),
    putModifierPrices: build.mutation<
      ProductAdminDetail,
      { variantId: string; items: ModifierPriceIn[] }
    >({
      query: ({ variantId, items }) => ({
        url: `admin/variants/${variantId}/modifier-prices`,
        method: 'PUT',
        body: items,
      }),
      invalidatesTags: [...PRODUCT_TAGS],
    }),
    putProductGroups: build.mutation<
      ProductAdminDetail,
      { productId: string; items: ProductGroupLink[] }
    >({
      query: ({ productId, items }) => ({
        url: `admin/products/${productId}/modifier-groups`,
        method: 'PUT',
        body: items,
      }),
      invalidatesTags: [...GROUP_TAGS],
    }),
    uploadProductImage: build.mutation<
      ProductAdminDetail,
      { productId: string; file: File; altText?: string; primary?: boolean }
    >({
      query: ({ productId, file, altText, primary }) => {
        const body = new FormData();
        body.append('file', file);
        if (altText) {
          body.append('alt_text', altText);
        }
        body.append('is_primary', primary ? 'true' : 'false');
        return { url: `admin/products/${productId}/images`, method: 'POST', body };
      },
      invalidatesTags: [...PRODUCT_TAGS],
    }),
    deleteProductImage: build.mutation<void, { productId: string; imageId: string }>({
      query: ({ productId, imageId }) => ({
        url: `admin/products/${productId}/images/${imageId}`,
        method: 'DELETE',
      }),
      invalidatesTags: [...PRODUCT_TAGS],
    }),

    // Modifier groups and modifiers
    adminGroups: build.query<ModifierGroupAdminList, void>({
      query: () => 'admin/modifier-groups',
      providesTags: ['AdminGroups'],
    }),
    createGroup: build.mutation<ModifierGroupAdminOut, ModifierGroupCreate>({
      query: (body) => ({ url: 'admin/modifier-groups', method: 'POST', body }),
      invalidatesTags: [...GROUP_TAGS],
    }),
    updateGroup: build.mutation<ModifierGroupAdminOut, { id: string; body: ModifierGroupUpdate }>({
      query: ({ id, body }) => ({ url: `admin/modifier-groups/${id}`, method: 'PATCH', body }),
      invalidatesTags: [...GROUP_TAGS],
    }),
    createModifier: build.mutation<ModifierAdminOut, ModifierCreate>({
      query: (body) => ({ url: 'admin/modifiers', method: 'POST', body }),
      invalidatesTags: [...GROUP_TAGS],
    }),
    updateModifier: build.mutation<ModifierAdminOut, { id: string; body: ModifierUpdate }>({
      query: ({ id, body }) => ({ url: `admin/modifiers/${id}`, method: 'PATCH', body }),
      invalidatesTags: [...GROUP_TAGS],
    }),
  }),
});

export const {
  useAdminCategoriesQuery,
  useCreateCategoryMutation,
  useUpdateCategoryMutation,
  useDeactivateCategoryMutation,
  useUploadCategoryImageMutation,
  useAdminProductsQuery,
  useAdminProductQuery,
  useCreateProductMutation,
  useUpdateProductMutation,
  useDeleteProductMutation,
  useAddVariantMutation,
  useUpdateVariantMutation,
  usePutModifierPricesMutation,
  usePutProductGroupsMutation,
  useUploadProductImageMutation,
  useDeleteProductImageMutation,
  useAdminGroupsQuery,
  useCreateGroupMutation,
  useUpdateGroupMutation,
  useCreateModifierMutation,
  useUpdateModifierMutation,
} = adminCatalogApi;
