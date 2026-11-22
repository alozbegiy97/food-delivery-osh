import { baseApi } from '../../shared/api/baseApi';
import type {
  CategoryList,
  ProductDetail,
  ProductList,
  RestaurantOut,
} from '../../shared/types/api';
import type { Language } from '../../shared/i18n/languages';

// The language is part of every query argument: switching the UI language
// requests the catalog again in that language (the API returns translations
// with fallback, API_SPECIFICATION.md §1.3).
export interface ProductListArgs {
  language: Language;
  categoryId?: string;
  search?: string;
  featured?: boolean;
  page?: number;
  pageSize?: number;
}

export const PRODUCTS_PAGE_SIZE = 12;

export const catalogApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getCategories: build.query<CategoryList, Language>({
      providesTags: ['Catalog'],
      query: (language) => ({ url: 'catalog/categories', params: { language } }),
    }),
    getProducts: build.query<ProductList, ProductListArgs>({
      providesTags: ['Catalog'],
      query: ({
        language,
        categoryId,
        search,
        featured,
        page = 1,
        pageSize = PRODUCTS_PAGE_SIZE,
      }) => ({
        url: 'catalog/products',
        params: {
          language,
          page,
          page_size: pageSize,
          ...(categoryId ? { category_id: categoryId } : {}),
          ...(search ? { search } : {}),
          ...(featured !== undefined ? { featured } : {}),
        },
      }),
    }),
    getProduct: build.query<ProductDetail, { id: string; language: Language }>({
      providesTags: ['Catalog'],
      query: ({ id, language }) => ({
        url: `catalog/products/${encodeURIComponent(id)}`,
        params: { language },
      }),
    }),
    getRestaurant: build.query<RestaurantOut, void>({
      providesTags: ['Catalog'],
      query: () => 'restaurant',
    }),
  }),
});

export const {
  useGetCategoriesQuery,
  useGetProductsQuery,
  useGetProductQuery,
  useGetRestaurantQuery,
} = catalogApi;
