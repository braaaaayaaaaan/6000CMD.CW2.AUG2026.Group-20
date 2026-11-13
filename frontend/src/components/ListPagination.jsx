import { Button, Flex, NativeSelect, Text } from "@chakra-ui/react";

export default function ListPagination({ page, count, pageSize = 40, onPageChange, onPageSizeChange, disabled = false }) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (pages === 1 && page === 1 && !onPageSizeChange) return null;
  return (
    <Flex as="nav" aria-label="List pagination" gap="3" align="center" justify="center" wrap="wrap" my="5">
      {onPageSizeChange && <Flex as="label" align="center" gap="2" fontSize="sm" color="gray.600">
        Rows per Page
        <NativeSelect.Root size="sm" width="80px" disabled={disabled}>
          <NativeSelect.Field value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
            {[10, 25, 40, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
          </NativeSelect.Field><NativeSelect.Indicator />
        </NativeSelect.Root>
      </Flex>}
      {onPageSizeChange && <Text fontSize="sm" color="gray.600">{count ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, count)} of ${count}` : "0 results"}</Text>}
      <Button variant="outline" disabled={disabled || page <= 1} onClick={() => onPageChange(page - 1)}>Previous</Button>
      <Text aria-live="polite">Page {page} of {Math.max(page, pages)}</Text>
      <Button variant="outline" disabled={disabled || page >= pages} onClick={() => onPageChange(page + 1)}>Next</Button>
    </Flex>
  );
}
