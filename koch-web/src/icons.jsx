// Einheitliches Icon-Set für die ganze App – dünner Wrapper um lucide-react.
// Nutzung: <Icon name="chef-hat" size={18} className="text-terracotta" />
// Vorteile: eine API, currentColor erbt die Textfarbe, ein zentraler Ort für Namen.
import {
  Check, CircleCheck, X, ShoppingCart, Sparkles, TriangleAlert, ChefHat, Tag,
  Image, Camera, PartyPopper, Settings, Calendar, Star, Trash2, Pencil, Bug,
  FileText, MessageCircle, Download, Upload, ChartColumn, Users, User, Wrench,
  Package, Moon, Sun, Sunrise, House, Store, Mic, Globe, Soup, Euro, Gift, Bot,
  Bell, Rocket, Apple, Backpack, RefreshCw, Recycle, SquarePen, AlarmClock,
  Timer, Utensils, Palette, Monitor, ArrowUp, ArrowRight, FlaskConical, Wand2,
  Lock, Zap, Volume2, ThumbsUp, Notebook, Megaphone, Printer, Link as LinkIcon, Mail,
  Smartphone, Hand, Circle, SlidersHorizontal, Lightbulb, Paperclip, CreditCard,
  Carrot, Ticket, Menu, BookOpen, ChevronRight, ChevronLeft, Plus, Search,
} from 'lucide-react'

const MAP = {
  // Navigation / Struktur
  home: House, 'book-open': BookOpen, calendar: Calendar, tag: Tag, menu: Menu,
  package: Package, users: Users, user: User, 'shopping-cart': ShoppingCart,
  'credit-card': CreditCard, settings: Settings, wrench: Wrench, tools: Wrench,
  'chevron-right': ChevronRight, 'chevron-left': ChevronLeft, plus: Plus,
  'arrow-right': ArrowRight, 'arrow-up': ArrowUp,
  store: Store, home2: House, notebook: Notebook, 'file-text': FileText,
  smartphone: Smartphone, monitor: Monitor, link: LinkIcon, paperclip: Paperclip,
  'sliders': SlidersHorizontal, lock: Lock, search: Search,
  // Status / Feedback
  check: Check, 'circle-check': CircleCheck, x: X, 'alert-triangle': TriangleAlert,
  star: Star, circle: Circle, bug: Bug, lightbulb: Lightbulb, zap: Zap,
  // Aktionen
  trash: Trash2, pencil: Pencil, edit: SquarePen, download: Download,
  upload: Upload, refresh: RefreshCw, recycle: Recycle, printer: Printer,
  // KI / Magie / Kommunikation
  sparkles: Sparkles, wand: Wand2, bot: Bot, 'message-circle': MessageCircle,
  mic: Mic, bell: Bell, megaphone: Megaphone, volume: Volume2, mail: Mail,
  // Küche / Essen
  'chef-hat': ChefHat, utensils: Utensils, soup: Soup, apple: Apple,
  carrot: Carrot, flask: FlaskConical,
  // Medien
  image: Image, camera: Camera, palette: Palette,
  // Zeit / Tag
  alarm: AlarmClock, timer: Timer, moon: Moon, sun: Sun, sunrise: Sunrise,
  // Sonstiges
  globe: Globe, euro: Euro, gift: Gift, rocket: Rocket, backpack: Backpack,
  'bar-chart': ChartColumn, 'party-popper': PartyPopper, 'thumbs-up': ThumbsUp,
  ticket: Ticket, hand: Hand,
}

export function Icon({ name, size = 24, className = '', strokeWidth = 2, ...rest }) {
  const C = MAP[name]
  if (!C) return null
  return <C size={size} className={className} strokeWidth={strokeWidth} aria-hidden="true" {...rest} />
}

// Cloche-Emblem (Servierglocke + Kräuter-Sprig + Schaltkreis-Knoten). Kupfer + Grün
// fest, da das Emblem in beiden Themes auf dunkler Kachel sitzt (wie ein App-Icon).
export function EmblemSvg({ size = 60, className = '' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" className={className} aria-hidden>
      <g stroke="#7bc492" strokeWidth="1.6" opacity=".7" strokeLinecap="round">
        <path d="M16 96h12M92 96h12M22 96v-8M98 96v-8" />
        <circle cx="22" cy="86" r="2.4" fill="#7bc492" stroke="none" />
        <circle cx="98" cy="86" r="2.4" fill="#7bc492" stroke="none" />
      </g>
      <path d="M28 86a32 32 0 0 1 64 0" stroke="#e3a86a" strokeWidth="5" strokeLinecap="round" />
      <circle cx="60" cy="48" r="4.5" fill="#e3a86a" />
      <path d="M60 52v6" stroke="#e3a86a" strokeWidth="4" strokeLinecap="round" />
      <path d="M52 70c8-11 16-11 24 0" stroke="#7bc492" strokeWidth="4.5" strokeLinecap="round" />
      <rect x="24" y="86" width="72" height="6" rx="3" fill="#e3a86a" />
    </svg>
  )
}

// Emblem-Kachel (dunkel, wie App-Icon) – in beiden Themes gleich.
export function LogoMark({ size = 40, className = '' }) {
  return (
    <span
      className={`login-emblem inline-flex shrink-0 items-center justify-center ${className}`}
      style={{ width: size, height: size, borderRadius: Math.round(size * 0.26) }}
      role="img" aria-label="Sapio"
    >
      <EmblemSvg size={Math.round(size * 0.62)} />
    </span>
  )
}

// Marke: Emblem-Kachel + Wortmarke (Kupfer-Verlauf). variant 'full' = zusätzlich Slogan.
export function Logo({ variant = 'emblem', className = '' }) {
  return (
    <div className={`flex flex-col items-center gap-3 ${className}`}>
      <LogoMark size={84} />
      <div className="text-center">
        <div className="sapio-wortmarke text-4xl leading-none">Sapio</div>
        {variant === 'full' && <div className="label-mono mt-2 text-terracotta">Genuss mit Verstand</div>}
      </div>
    </div>
  )
}
