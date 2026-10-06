import CrimeClient from "./CrimeClient";

async function getCrimeReport() {
  try {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/crime/report`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function CrimePage() {
  const initialData = await getCrimeReport();
  return <CrimeClient initialData={initialData} />;
}