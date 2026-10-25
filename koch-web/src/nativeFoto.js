// Native Kamera (Capacitor) – nur nativ genutzt; im Web bleibt der <input capture>.
// Gibt eine File (JPEG) zurück oder null (Abbruch). Camera.getPhoto fragt Rechte selbst ab.
import { IST_NATIVE } from './native.js'

export async function nativeFoto() {
  if (!IST_NATIVE) return null
  const { Camera, CameraResultType, CameraSource } = await import('@capacitor/camera')
  try {
    const photo = await Camera.getPhoto({
      quality: 82,
      resultType: CameraResultType.Uri,
      source: CameraSource.Prompt,     // Kamera ODER Galerie wählen
      promptLabelHeader: 'Foto',
      promptLabelPhoto: 'Aus Galerie',
      promptLabelPicture: 'Kamera',
    })
    if (!photo?.webPath) return null
    const blob = await (await fetch(photo.webPath)).blob()
    return new File([blob], 'foto.jpg', { type: blob.type || 'image/jpeg' })
  } catch (e) {
    // Nutzer-Abbruch o.ä. -> null (kein Fehler-Toast)
    return null
  }
}
