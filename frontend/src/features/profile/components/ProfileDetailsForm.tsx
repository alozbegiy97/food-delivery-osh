import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';

import { apiErrorInfo } from '../../../shared/api/errors';
import { TextField } from '../../../shared/components/TextField';
import { formatPhoneInput } from '../../../shared/lib/phone';
import { zodResolver } from '../../../shared/lib/zodResolver';
import type { MeResponse } from '../../../shared/types/api';
import { FormAlert, SubmitButton } from '../../auth/components/AuthCard';
import { useApiErrorText } from '../../auth/useApiErrorText';
import { useUpdateProfileMutation } from '../profileApi';
import { profileDetailsSchema, type ProfileDetailsValues } from '../validation';

/** Fields of PATCH /users/me this form may send: never null, never the language. */
interface DetailsChange {
  full_name?: string;
  phone?: string;
}

/** Server field errors (422 `details`) shown under the matching input. */
const SERVER_FIELD_MESSAGES = {
  full_name: 'validation.nameInvalid',
  phone: 'validation.phoneInvalid',
} as const;

function isFormField(field: string): field is keyof typeof SERVER_FIELD_MESSAGES {
  return field in SERVER_FIELD_MESSAGES;
}

interface ProfileDetailsFormProps {
  profile: MeResponse;
  /** Called only after the backend confirmed the change. */
  onSaved: () => void;
  /** Cancel, or nothing changed: closed without a request. */
  onClose: () => void;
}

/**
 * Inline form for the name and the phone of the Mini App profile
 * (DEC-160 п. 2, DEC-141). The initial values are taken once, when the form
 * opens: a later reload of the profile (e.g. after a language change in the
 * header) does not reset what was typed. Only changed fields are sent; an
 * empty phone of a profile without one is not sent at all, `phone: null` is
 * never sent and the language is never part of the request.
 */
export function ProfileDetailsForm({ profile, onSaved, onClose }: ProfileDetailsFormProps) {
  const { t } = useTranslation();
  const errorText = useApiErrorText();
  const [updateProfile, { isLoading, error }] = useUpdateProfileMutation();
  const [initial] = useState<ProfileDetailsValues>(() => ({
    full_name: profile.full_name,
    phone: profile.phone ? formatPhoneInput(profile.phone) : '',
  }));
  const [schema] = useState(() => profileDetailsSchema(initial.phone !== ''));
  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<ProfileDetailsValues>({
    resolver: zodResolver(schema),
    defaultValues: initial,
  });

  const onSubmit = handleSubmit(async (values) => {
    const change: DetailsChange = {};
    if (values.full_name !== initial.full_name) {
      change.full_name = values.full_name;
    }
    // Both sides are in the mask format, so equal numbers compare equal.
    if (values.phone !== '' && values.phone !== initial.phone) {
      change.phone = values.phone;
    }
    if (Object.keys(change).length === 0) {
      onClose();
      return;
    }
    try {
      await updateProfile(change).unwrap();
    } catch (failure) {
      const info = apiErrorInfo(failure as Parameters<typeof apiErrorInfo>[0]);
      if (info?.code === 'VALIDATION_ERROR') {
        for (const { field } of info.fields) {
          if (isFormField(field)) {
            setError(field, { type: 'server', message: SERVER_FIELD_MESSAGES[field] });
          }
        }
      }
      return; // the form stays open with the typed values
    }
    onSaved();
  });

  const info = apiErrorInfo(error);
  const shownUnderFields =
    info?.code === 'VALIDATION_ERROR' && info.fields.some(({ field }) => isFormField(field));
  const fieldError = (message?: string) => (message ? t(message) : undefined);

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
      {error && !shownUnderFields && <FormAlert>{errorText(error)}</FormAlert>}
      <TextField
        label={t('auth.fields.fullName')}
        autoComplete="name"
        error={fieldError(errors.full_name?.message)}
        {...register('full_name')}
      />
      <Controller
        control={control}
        name="phone"
        render={({ field }) => (
          <TextField
            label={t('account.phone')}
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+996 700 12 34 56"
            hint={t('auth.hints.phone')}
            error={fieldError(errors.phone?.message)}
            name={field.name}
            ref={field.ref}
            value={field.value}
            onBlur={field.onBlur}
            onChange={(event) => field.onChange(formatPhoneInput(event.target.value))}
          />
        )}
      />
      <div className="flex flex-wrap gap-3">
        <SubmitButton pending={isLoading}>
          {isLoading ? t('telegram.profile.saving') : t('telegram.profile.save')}
        </SubmitButton>
        <button
          type="button"
          onClick={onClose}
          disabled={isLoading}
          className="min-h-11 rounded-md border border-border px-4 py-2 font-semibold text-ink-900 focus:outline-2 focus:outline-offset-2 focus:outline-accent-600 disabled:opacity-60"
        >
          {t('telegram.profile.cancel')}
        </button>
      </div>
    </form>
  );
}
