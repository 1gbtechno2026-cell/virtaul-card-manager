const ONES = [
  '', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
  'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
  'Seventeen', 'Eighteen', 'Nineteen',
]
const TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

function twoDigitsToWords(n) {
  if (n < 20) return ONES[n]
  const t = Math.floor(n / 10)
  const o = n % 10
  return TENS[t] + (o ? ' ' + ONES[o] : '')
}

function threeDigitsToWords(n) {
  const hundred = Math.floor(n / 100)
  const rest = n % 100
  let out = ''
  if (hundred) out += ONES[hundred] + ' Hundred'
  if (rest) out += (out ? ' ' : '') + twoDigitsToWords(rest)
  return out
}

// Converts a number to words using the Indian numbering system
// (thousand, lakh, crore) e.g. 600000 -> "Six Lakh Rupees Only"
export function numberToIndianWords(value) {
  const num = Math.floor(Math.abs(Number(value)))
  if (!Number.isFinite(num)) return ''
  if (num === 0) return 'Zero Rupees Only'

  let remaining = num
  const crore = Math.floor(remaining / 10000000)
  remaining %= 10000000
  const lakh = Math.floor(remaining / 100000)
  remaining %= 100000
  const thousand = Math.floor(remaining / 1000)
  remaining %= 1000
  const hundred = remaining

  const parts = []
  if (crore) parts.push(threeDigitsToWords(crore) + ' Crore')
  if (lakh) parts.push(threeDigitsToWords(lakh) + ' Lakh')
  if (thousand) parts.push(threeDigitsToWords(thousand) + ' Thousand')
  if (hundred) parts.push(threeDigitsToWords(hundred))

  return parts.join(' ') + ' Rupees Only'
}

// Formats a number with Indian-style comma grouping, e.g. 600000 -> "6,00,000"
export function formatIndianNumber(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return String(value ?? '')
  return num.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}
