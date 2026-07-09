import { useState, useRef, useEffect } from 'react'
import { ChevronDownIcon } from 'lucide-react'
import './select.css'

export interface SelectItemType {
  id: string
  label: string
  supportingText?: string
  disabled?: boolean
  icon?: React.ReactNode
}

interface SelectProps {
  label?: string
  tooltip?: string
  hint?: string
  placeholder?: string
  items: SelectItemType[]
  selectedKey?: string
  onSelectionChange?: (key: string) => void
  isRequired?: boolean
  isDisabled?: boolean
  children?: (item: SelectItemType) => React.ReactNode
}

function Select({
  label,
  tooltip,
  hint,
  placeholder = 'Select...',
  items,
  selectedKey,
  onSelectionChange,
  isRequired = false,
  isDisabled = false,
  children,
}: SelectProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const selected = items.find((i) => i.id === selectedKey)
  const displayText = selected ? selected.label : placeholder

  return (
    <div className="sel-root" ref={ref}>
      {label && (
        <label className="sel-label">
          {label}
          {isRequired && <span className="sel-required">*</span>}
          {tooltip && <span className="sel-tooltip" title={tooltip}>?</span>}
        </label>
      )}
      <button
        className={`sel-trigger ${open ? 'sel-trigger--open' : ''}`}
        type="button"
        disabled={isDisabled}
        onClick={() => setOpen(!open)}
      >
        <span className={selected ? 'sel-value' : 'sel-placeholder'}>
          {displayText}
        </span>
        <ChevronDownIcon size={14} className={`sel-chevron ${open ? 'sel-chevron--open' : ''}`} />
      </button>
      {hint && <p className="sel-hint">{hint}</p>}
      {open && (
        <div className="sel-popover">
          {items.map((item) => {
            const itemEl = children ? (
              children(item)
            ) : (
              <SelectItem id={item.id} supportingText={item.supportingText} isDisabled={item.disabled}>
                {item.label}
              </SelectItem>
            )

            return (
              <div
                key={item.id}
                className={`sel-item ${item.disabled ? 'sel-item--disabled' : ''} ${item.id === selectedKey ? 'sel-item--selected' : ''}`}
                onClick={() => {
                  if (!item.disabled && onSelectionChange) {
                    onSelectionChange(item.id)
                    setOpen(false)
                  }
                }}
              >
                {item.icon && <span className="sel-item-icon">{item.icon}</span>}
                <div className="sel-item-body">
                  <span className="sel-item-label">{item.label}</span>
                  {item.supportingText && (
                    <span className="sel-item-support">{item.supportingText}</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

interface SelectItemProps {
  id: string
  supportingText?: string
  isDisabled?: boolean
  icon?: React.ReactNode
  children: React.ReactNode
}

function SelectItem(_props: SelectItemProps) {
  return null
}

Select.Item = SelectItem

export { Select }
export default Select
