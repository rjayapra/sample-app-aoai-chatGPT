import { CommandBarButton, DefaultButton, IButtonProps, IToggleProps } from '@fluentui/react'
import { Toggle } from '@fluentui/react'

import styles from './Button.module.css'

interface ButtonProps extends IButtonProps {
  onClick: () => void
  text: string | undefined
}

interface ToggleProps extends IToggleProps {
  onChange?: (ev?: React.FormEvent<HTMLElement>, checked?: boolean) => void
  label: string
  onText: string
  offText: string
  defaultChecked?: boolean
  checked?: boolean  
}
 

export const ToggleButton: React.FC<ToggleProps> = ({ onChange, onText,offText }) => {
  return (
    <Toggle
      className={styles.toggleButtonRoot}
      onText={onText}
      offText={offText}
      onChange={onChange}
    />
  )
}   


export const ShareButton: React.FC<ButtonProps> = ({ onClick, text }) => {
  return (
    <CommandBarButton
      className={styles.shareButtonRoot}
      iconProps={{ iconName: 'Share' }}
      onClick={onClick}
      text={text}
    />
  )
}

export const HistoryButton: React.FC<ButtonProps> = ({ onClick, text }) => {
  return (
    <DefaultButton
      className={styles.historyButtonRoot}
      text={text}
      iconProps={{ iconName: 'History' }}
      onClick={onClick}
    />
  )
}
