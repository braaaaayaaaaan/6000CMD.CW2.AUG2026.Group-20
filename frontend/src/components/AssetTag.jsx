import { Button, Flex, Spinner, Tag, Text } from "@chakra-ui/react";
import { HiPlus } from "react-icons/hi";

export default function AssetTag({ tags, loading, error, selectedTags, onSelectTag, disabled = false, onRetry }) {
  if (loading) return <Spinner size="lg" color="blue.700" aria-label="Loading tags" />;
  if (error) return (
    <Flex gap="2" align="center" wrap="wrap">
      <Text role="alert">{error}</Text>
      {onRetry && <Button type="button" size="xs" variant="outline" onClick={onRetry}>Retry tags</Button>}
    </Flex>
  );
  return (
    <Flex gap="2" wrap="wrap">
      {tags.length ? tags.map((tag) => (
        <Tag.Root as="button" type="button" key={tag.id} size="lg" aria-pressed={selectedTags.includes(tag.id)}
          bg={selectedTags.includes(tag.id) ? "blue.700" : "gray.100"}
          color={selectedTags.includes(tag.id) ? "white" : "black"}
          _hover={{ cursor: disabled ? "not-allowed" : "pointer", opacity: 0.8 }}
          _disabled={{ opacity: 0.5 }}
          disabled={disabled} onClick={() => onSelectTag(tag.id)}>
          {!selectedTags.includes(tag.id) && <HiPlus style={{ marginRight: 4 }} />}
          <Tag.Label>{tag.title}</Tag.Label>
        </Tag.Root>
      )) : <Text>No tags found!</Text>}
    </Flex>
  );
}
