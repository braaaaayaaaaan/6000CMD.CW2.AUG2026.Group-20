'use client'

import {
  Box,
  HStack,
  IconButton,
  Input,
  InputGroup,
  Stack,
  Text,
  mergeRefs,
  useControllableState,
} from '@chakra-ui/react'
import * as React from 'react'
import { LuCheck, LuCircle, LuEye, LuEyeOff } from 'react-icons/lu'

export const PasswordInput = React.forwardRef(
  function PasswordInput(props, ref) {
    const {
      rootProps,
      defaultVisible,
      visible: visibleProp,
      onVisibleChange,
      visibilityIcon = { on: <LuEye />, off: <LuEyeOff /> },
      ...rest
    } = props

    const [visible, setVisible] = useControllableState({
      value: visibleProp,
      defaultValue: defaultVisible || false,
      onChange: onVisibleChange,
    })

    const inputRef = React.useRef(null)

    return (
      <InputGroup
        endElement={
          <VisibilityTrigger
            disabled={rest.disabled}
            onClick={() => setVisible(!visible)}
            aria-pressed={visible}
          >
            {visible ? visibilityIcon.off : visibilityIcon.on}
          </VisibilityTrigger>
        }
        {...rootProps}
      >
        <Input
          {...rest}
          ref={mergeRefs(ref, inputRef)}
          type={visible ? 'text' : 'password'}
        />
      </InputGroup>
    )
  },
)

const VisibilityTrigger = React.forwardRef(
  function VisibilityTrigger(props, ref) {
    return (
      <IconButton
        type='button'
        ref={ref}
        me='-2'
        aspectRatio='square'
        size='sm'
        variant='ghost'
        height='calc(100% - {spacing.2})'
        aria-label='Toggle Password Visibility'
        {...props}
      />
    )
  },
)

export const PasswordStrengthMeter = React.forwardRef(
  function PasswordStrengthMeter(props, ref) {
    const { max = 4, value, label: customLabel, ...rest } = props

    const percent = (value / max) * 100
    const { label: defaultLabel, colorPalette } = getColorPalette(percent)
    const label = customLabel ?? defaultLabel

    return (
      <Stack align='flex-end' gap='1' ref={ref} role='meter' aria-label='Estimated Password Strength'
        aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-valuetext={label} {...rest}>
        <HStack width='full'>
          {Array.from({ length: max }).map((_, index) => (
            <Box
              key={index}
              height='1'
              flex='1'
              rounded='sm'
              data-selected={index < value ? '' : undefined}
              layerStyle='fill.subtle'
              colorPalette='blue'
              _selected={{
                colorPalette,
                layerStyle: 'fill.solid',
              }}
            />
          ))}
        </HStack>
        {label && <HStack textStyle='xs'>{label}</HStack>}
      </Stack>
    )
  },
)

export function PasswordStrengthFeedback({ id, password = '', confirmation = '', minLength = 12, compact = false }) {
  const characters = Array.from(password)
  const lengthMet = characters.length >= minLength
  const decimalOnly = /^\p{Decimal_Number}+$/u.test(password)
  const hasNonNumber = /\P{Number}/u.test(password)
  const uniqueCharacters = new Set(characters.map((character) => character.toLowerCase())).size
  const predictable = /(.)\1{3,}|1234|2345|3456|4567|5678|6789|abcd|qwerty|asdf|password|letmein|welcome/iu.test(password)
  const variety = [/\p{Lowercase_Letter}/u, /\p{Uppercase_Letter}/u, /\p{Decimal_Number}/u, /[^\p{Letter}\p{Number}\s]/u]
    .filter((pattern) => pattern.test(password)).length

  let strength = 0
  if (password) {
    strength = 1
    if (lengthMet && uniqueCharacters >= 5) strength = 2
    if (lengthMet && uniqueCharacters >= 8 && (characters.length >= 16 || variety >= 3)) strength = 3
    if (uniqueCharacters >= 10 && (characters.length >= 20 || (characters.length >= 16 && variety >= 3))) strength = 4
    if (!lengthMet || decimalOnly || predictable) strength = 1
  }

  const suggestions = []
  if (characters.length < 16) suggestions.push('try 16 or more characters')
  if (!/\p{Decimal_Number}/u.test(password)) suggestions.push('add a number')
  if (!/[^\p{Letter}\p{Number}\s]/u.test(password)) suggestions.push('add a symbol')
  if (predictable) suggestions.push('avoid repeated or predictable patterns')

  let nonNumericMet = null
  if (hasNonNumber) nonNumericMet = true
  if (decimalOnly) nonNumericMet = false
  const requirements = [
    { id: 'length', label: `At Least ${minLength} Characters (${characters.length}/${minLength})`, met: password ? lengthMet : null },
    { id: 'non-numeric', label: 'Must Not Be Entirely Numeric', met: nonNumericMet },
    { id: 'confirmation', label: 'Passwords Match', met: confirmation ? password === confirmation : null },
  ]
  const strengthLabel = password ? ['Weak', 'Fair', 'Good', 'Strong'][strength - 1] : 'Not Entered'

  if (compact) {
    const hints = []
    if (!password) hints.push(`Use at least ${minLength} characters. Avoid common passwords and personal details.`)
    if (password && !lengthMet) hints.push(`Add ${minLength - characters.length} more characters.`)
    if (decimalOnly) hints.push('Include a letter or symbol.')
    if (confirmation && password !== confirmation) hints.push('Passwords do not match yet.')
    if (password && predictable) hints.push('Try a less predictable password.')

    return (
      <Stack id={id} as='section' aria-label='Password Requirements' w='full' gap='2' textAlign='left'>
        {password && <PasswordStrengthMeter value={strength} label={strengthLabel} w='full' />}
        {hints.length > 0 && <Text fontSize='xs' color='fg.muted' aria-live='polite'>{hints.join(' ')}</Text>}
      </Stack>
    )
  }

  return (
    <Stack id={id} as='section' aria-label='Password Requirements' w='full' gap='3'
      textAlign='left' bg='blue.50' color='fg' borderWidth='1px' borderColor='blue.100'
      borderRadius='md' p='4'>
      <HStack justify='space-between' gap='2' flexWrap='wrap'>
        <Text fontSize='sm' fontWeight='semibold' color='blue.700'>Password Requirements</Text>
        <Text fontSize='xs' fontWeight='medium' aria-live='polite'>
          Estimated Strength · {strengthLabel}
        </Text>
      </HStack>
      <PasswordStrengthMeter w='full' value={strength} label='' aria-valuetext={strengthLabel} />
      <Stack as='ul' gap='2' listStyleType='none' m='0' p='0'>
        {requirements.map(({ id: requirementId, label, met }) => {
          const Icon = met === true ? LuCheck : LuCircle
          const color = met === null ? 'fg.muted' : 'blue.700'
          const status = met === true ? 'Met' : met === false ? 'Not Met' : 'Pending'
          return (
            <HStack as='li' key={requirementId} gap='2' align='start' color={color} fontSize='xs'>
              <Box as='span' pt='0.5' flexShrink='0'><Icon aria-hidden='true' /></Box>
              <Text>{label}<Box as='span' srOnly> — {status}</Box></Text>
            </HStack>
          )
        })}
      </Stack>
      <Box borderTopWidth='1px' borderColor='blue.100' pt='2'>
        <Text fontSize='xs' fontWeight='medium' mb='1'>Also Checked When Saved</Text>
        <Text fontSize='xs' color='fg.muted'>Avoid common passwords and passwords similar to your name, username or email.</Text>
      </Box>
      {password && strength < 4 && suggestions.length > 0 && (
        <Box>
          <Text fontSize='xs' fontWeight='medium'>Strength Tips (Optional)</Text>
          <Text fontSize='xs' color='fg.muted'>{suggestions.join(' · ')}</Text>
        </Box>
      )}
    </Stack>
  )
}

function getColorPalette(percent) {
  switch (true) {
    case percent < 33:
      return { label: 'Low', colorPalette: 'blue' }
    case percent < 66:
      return { label: 'Medium', colorPalette: 'blue' }
    default:
      return { label: 'High', colorPalette: 'blue' }
  }
}
