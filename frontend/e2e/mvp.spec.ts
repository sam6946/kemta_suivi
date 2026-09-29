import { expect, test } from "@playwright/test";

const DEMO_PHONE = "+237690000003";
const RESET_PASSWORD = "Chantier#2026Kribi";

test("MVP-017 : réinitialiser le mot de passe par SMS puis ouvrir le tableau projet", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/connexion");
  await page.getByRole("link", { name: "Mot de passe oublié ?" }).click();

  await page.getByLabel("Numéro de téléphone").fill(DEMO_PHONE);
  await page.getByRole("button", { name: "Recevoir un code par SMS" }).click();
  await expect(page.getByText(/Si ce numéro est associé à un compte KEMTA/)).toBeVisible();
  await page.getByTestId("continue-to-reset").click();

  await expect(page.getByRole("heading", { name: "Nouveau mot de passe" })).toBeVisible();
  await page.getByRole("button", { name: /Afficher les codes de test/ }).click();
  const useCode = page.getByRole("button", { name: /Utiliser \d{6}/ }).first();
  await expect(useCode).toBeVisible();
  await useCode.click();
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill(RESET_PASSWORD);
  await page.getByLabel("Confirmer le mot de passe").fill(RESET_PASSWORD);
  await page.getByRole("button", { name: "Réinitialiser mon mot de passe" }).click();

  await expect(page.getByRole("heading", { name: "Mot de passe réinitialisé" })).toBeVisible();
  await page.getByRole("link", { name: "Aller à la connexion" }).click();
  await page.getByLabel("Numéro de téléphone").fill(DEMO_PHONE);
  await page.getByLabel("Mot de passe").fill(RESET_PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL(/\/tableau-de-bord$/);

  await page.getByRole("link", { name: "Voir mes projets" }).click();
  await page.getByRole("link", { name: /Résidence Bonamoussadi/ }).click();
  await page.getByRole("link", { name: "Tableau de bord agrégé" }).click();
  await expect(page.getByRole("heading", { name: "Tableau de bord du projet" })).toBeVisible();
  await expect(page.getByText("Avancement global")).toBeVisible();
});

test("MVP-001 : l'inscription utilise le téléphone sans exiger d'email", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/inscription");
  await expect(page.getByLabel("Numéro de téléphone")).toBeVisible();
  await expect(page.locator('input[type="email"]')).toHaveCount(0);
});
