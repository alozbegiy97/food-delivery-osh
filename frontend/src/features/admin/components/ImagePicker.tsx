import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { BUTTON_SECONDARY } from './AdminUi';

// Client-side pre-check only for a quick hint; the backend checks the real
// content, type, extension and size (DEC-70).
const ACCEPT = 'image/jpeg,image/png,image/webp';
const MAX_BYTES = 5 * 1024 * 1024;

interface ImagePickerProps {
  label: string;
  pending: boolean;
  onUpload: (file: File) => void;
}

export function ImagePicker({ label, pending, onUpload }: ImagePickerProps) {
  const { t } = useTranslation();
  const id = useId();
  const [problem, setProblem] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className={`${BUTTON_SECONDARY} cursor-pointer self-start`}>
        {pending ? t('admin.images.uploading') : label}
      </label>
      <input
        id={id}
        type="file"
        accept={ACCEPT}
        disabled={pending}
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (!file) {
            return;
          }
          if (!ACCEPT.split(',').includes(file.type)) {
            setProblem(t('admin.images.wrongType'));
            return;
          }
          if (file.size > MAX_BYTES) {
            setProblem(t('admin.images.tooBig'));
            return;
          }
          setProblem(null);
          onUpload(file);
        }}
      />
      <p className="text-xs text-ink-600">{t('admin.images.hint')}</p>
      {problem && (
        <p role="alert" className="text-sm text-danger-700">
          {problem}
        </p>
      )}
    </div>
  );
}
