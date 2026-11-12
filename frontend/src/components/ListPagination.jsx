import { Button, Flex, Text } from "@chakra-ui/react";

export default function ListPagination({ page, count, pageSize = 40, onPageChange, disabled = false }) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (pages === 1 && page === 1) return null;
  return (
    <Flex as="nav" aria-label="List pagination" gap="3" align="center" justify="center" wrap="wrap" my="5">
      <Button variant="outline" disabled={disabled || page <= 1} onClick={() => onPageChange(page - 1)}>Previous</Button>
      <Text aria-live="polite">Page {page} of {Math.max(page, pages)}</Text>
      <Button variant="outline" disabled={disabled || page >= pages} onClick={() => onPageChange(page + 1)}>Next</Button>
    </Flex>
  );
}
