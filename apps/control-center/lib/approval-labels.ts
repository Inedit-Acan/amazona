// Nombres legibles de las acciones con efecto y de los pasos del pipeline (Milestone 33, plan maestro §7). Sin datos de demostración.

/** Nombre legible de cada acción con efecto (Milestone 33, plan maestro §7). */
export const SIDE_EFFECT_LABELS: Record<string, string> = {
  publish_product: "publicar el producto",
  activate_ads: "activar la publicidad",
  spend_money: "gastar dinero",
  purchase_supplier: "comprar al proveedor",
  make_payment: "realizar el pago",
  ship_order: "enviar el pedido",
  refund: "hacer el reembolso",
  change_price: "cambiar el precio",
  send_contract_communication: "enviar la comunicación contractual",
};

export const PIPELINE_STEP_LABELS: Record<string, string> = {
  research: "Investigación",
  sourcing: "Proveedores",
  economics: "Economía",
  legal: "Legal",
  ecommerce: "Tienda",
  marketplace: "Marketplace",
  marketing: "Marketing",
  operations: "Operaciones",
  cfo: "CFO",
};
