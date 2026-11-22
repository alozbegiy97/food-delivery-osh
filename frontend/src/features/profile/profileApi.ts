import { baseApi } from '../../shared/api/baseApi';
import type { MeResponse, ProfileUpdate } from '../../shared/types/api';

// Own profile: GET/PATCH /users/me (API §4, DEC-152 п. 9, DEC-153). The body
// is that of GET /auth/me, so both share the `Me` tag.
export const profileApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getProfile: build.query<MeResponse, void>({
      query: () => 'users/me',
      providesTags: ['Me'],
    }),
    updateProfile: build.mutation<MeResponse, ProfileUpdate>({
      query: (body) => ({ url: 'users/me', method: 'PATCH', body }),
      invalidatesTags: ['Me'],
    }),
  }),
});

export const { useGetProfileQuery, useUpdateProfileMutation } = profileApi;
