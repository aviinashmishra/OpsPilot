import { Activity, BarChart3, Calendar, Kanban, LifeBuoy, type LucideIcon, Mail, MessageSquare, Package, Phone, Plug, Receipt, ShoppingBag, Star, Users } from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  users: Users,
  mail: Mail,
  "message-square": MessageSquare,
  kanban: Kanban,
  "life-buoy": LifeBuoy,
  "shopping-bag": ShoppingBag,
  receipt: Receipt,
  phone: Phone,
  calendar: Calendar,
  activity: Activity,
  package: Package,
  star: Star,
  "bar-chart": BarChart3,
};

export function integrationIcon(icon: string | undefined): LucideIcon {
  return (icon && ICONS[icon]) || Plug;
}
