'use client'

import {
  Toaster as ChakraToaster,
  Portal,
  Spinner,
  Stack,
  Toast,
  createToaster,
} from '@chakra-ui/react'
import { isAssetProcessing } from '@/utils/assetFiles'

export const toaster = createToaster({
  placement: 'bottom-end',
  pauseOnPageIdle: true,
  max: 3,
})

export function uploadToast(id, options) {
  const settings = { duration: 4000, closable: true, ...options }
  if (toaster.isVisible(id)) toaster.update(id, settings)
  else toaster.create({ id, ...settings })
}

export function notifyUploadStatus(asset, { toastId, previousApproved = false } = {}) {
  const replacement = asset.version_no > 1
  const status = asset.processing_status
  const description = status === 'approved'
    ? replacement ? 'New version is ready!' : 'File is ready!'
    : status === 'rejected'
      ? replacement && previousApproved
        ? 'New version rejected. Previous version is still available.'
        : replacement ? "New version couldn't be accepted." : "File couldn't be accepted."
      : status === 'error'
        ? "Couldn't process file. Please try again later."
        : replacement ? 'New version uploaded. Checking…' : 'Uploaded! Checking file…'
  uploadToast(toastId || 'asset-processing-' + asset.id, {
    title: asset.name,
    description,
    type: status === 'approved' ? 'success' : isAssetProcessing(asset) ? 'info' : 'error',
    duration: ['rejected', 'error'].includes(status) ? 6500 : 4000,
  })
}

export const Toaster = () => {
  return (
    <Portal>
      <ChakraToaster toaster={toaster} insetInline={{ mdDown: '4' }}>
        {(toast) => (
          <Toast.Root width={{ base: 'calc(100vw - 2rem)', md: 'sm' }} maxW='sm'
            rounded='xl' borderWidth='1px' boxShadow='md' p='3'
            css={{ '@media (prefers-reduced-motion: reduce)': { animation: 'none !important', transition: 'none !important' } }}>
            {toast.type === 'loading' ? (
              <Spinner size='sm' color='white' css={{ '@media (prefers-reduced-motion: reduce)': { animation: 'none' } }} />
            ) : (
              <Toast.Indicator />
            )}
            <Stack gap='1' flex='1' minW='0' maxWidth='100%'>
              {toast.title && <Toast.Title truncate>{toast.title}</Toast.Title>}
              {toast.description && (
                <Toast.Description overflowWrap='anywhere'>{toast.description}</Toast.Description>
              )}
            </Stack>
            {toast.action && (
              <Toast.ActionTrigger>{toast.action.label}</Toast.ActionTrigger>
            )}
            {toast.closable && <Toast.CloseTrigger />}
          </Toast.Root>
        )}
      </ChakraToaster>
    </Portal>
  )
}
