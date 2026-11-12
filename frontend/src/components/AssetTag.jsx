import { Button, Flex, Spinner, Text } from "@chakra-ui/react";

export default function AssetTag({ tags, loading, error, selectedTags, onSelectTag, disabled = false, onRetry }) {
  if (loading) return <Spinner size="sm" aria-label="Loading tags" />;
  if (error) return (
    <Flex gap="2" align="center" wrap="wrap">
      <Text role="alert">{error}</Text>
      {onRetry && <Button type="button" size="xs" onClick={onRetry}>Retry tags</Button>}
    </Flex>
  );
  return (
    <Flex gap="2" wrap="wrap">
      {tags.length ? tags.map((tag) => (
        <Button type="button" key={tag.id} size="sm" aria-pressed={selectedTags.includes(tag.id)}
          colorPalette="blue" variant={selectedTags.includes(tag.id) ? "solid" : "outline"}
          disabled={disabled} onClick={() => onSelectTag(tag.id)}>
          {tag.title}
        </Button>
      )) : <Text>No tags available.</Text>}
    </Flex>
  );
}
