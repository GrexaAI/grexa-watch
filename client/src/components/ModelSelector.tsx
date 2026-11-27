"use client";

import React, { useState, useEffect, useMemo } from 'react';
import { Button } from "@/components/ui/button";
import { Brain, ChevronDown } from 'lucide-react';
import { useQuery, jsonFetcher } from '@/lib/query';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface ModelOption {
  id: string;
  name: string;
  displayName: string;
  provider: string;
  tier: 'free' | 'pro' | 'premium';
  contextLength: string;
  hasReasoning: boolean;
  isSlow?: boolean;
}

interface ModelSelectorProps {
  selectedModel: string;
  onModelChange: (modelId: string) => void;
  className?: string;
  disabled?: boolean;
}

// Pricing information mapping (input/output per 1M tokens)
const modelPricing: Record<string, string> = {
  'openai/gpt-6.1-terra': '$1 input / $5 output per 1M tokens (OpenAI Standard estimate)',
  'openai/gpt-6-luna': '$0.1 input / $0.5 output per 1M tokens (OpenAI Standard estimate)',
};

type ModelTier = ModelOption['tier'];
type ModelOverrides = Partial<Pick<ModelOption, 'hasReasoning' | 'isSlow' | 'contextLength'>>;

// Display label for each id prefix, so rows below don't repeat the provider name.
const providerLabels: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  vertex: 'Vertex',
};

// Catalog rows: [id, displayName, tier, overrides?]. `name`, `provider`, and the
// 1M context / reasoning defaults are derived from the id below, so adding a model
// stays a one-liner instead of another near-identical object literal.
const modelCatalog: Array<[string, string, ModelTier, ModelOverrides?]> = [
  ['openai/gpt-6.1-terra', 'GPT-6.1 Terra', 'pro'],
  ['openai/gpt-6-luna', 'GPT-6 Luna', 'free'],
];

const modelOptions: ModelOption[] = modelCatalog.map(([id, displayName, tier, overrides]) => {
  const [prefix, name] = id.split('/');
  return {
    id,
    name,
    displayName,
    provider: providerLabels[prefix] ?? prefix,
    tier,
    contextLength: '1M',
    hasReasoning: true,
    ...overrides,
  };
});

interface PickerConfig {
  prefixes: string[] | null;
}

function modelsForPrefixes(prefixes: string[] | null): ModelOption[] {
  // OpenRouter / no keys: full catalog minus Vertex-only ids (those are not Google AI / OpenRouter picks).
  if (!prefixes) {
    return modelOptions.filter((m) => m.id.split('/')[0] !== 'vertex');
  }

  const out: ModelOption[] = [];
  for (const model of modelOptions) {
    const prefix = model.id.split('/')[0];
    if (prefix === 'openai' && prefixes.includes('openai')) {
      out.push(model);
    } else if (prefix === 'anthropic' && (prefixes.includes('anthropic') || prefixes.includes('bedrock'))) {
      out.push(model);
    } else if (prefix === 'google') {
      if (prefixes.includes('google')) out.push(model);
      if (prefixes.includes('vertex')) {
        out.push({ ...model, id: `vertex/${model.name}` });
      }
    } else if (prefix === 'vertex' && prefixes.includes('vertex')) {
      out.push(model);
    }
  }
  return out;
}

export default function ModelSelector({ 
  selectedModel, 
  onModelChange, 
  className = "", 
  disabled = false 
}: ModelSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const { data: picker, error: pickerError } = useQuery<PickerConfig>(
    '/api/llm-config/picker',
    jsonFetcher,
    { staleTime: 60_000 },
  );
  const visibleModels = useMemo(() => {
    if (pickerError) return modelsForPrefixes(null);
    if (!picker) return [];
    return modelsForPrefixes(picker.prefixes);
  }, [picker, pickerError]);

  // Load saved model from localStorage on mount, then drop anything this
  // deployment cannot actually serve (e.g. GPT under Vertex). Only reconcile
  // once the picker config is known: the error fallback catalog is display-only,
  // so persisting against it would discard a valid saved choice (e.g. Vertex).
  useEffect(() => {
    if (!picker) return;

    const catalog = visibleModels;
    if (catalog.length === 0) return;

    const savedModel = localStorage.getItem('selectedModel');
    const savedName = savedModel?.split('/')[1];
    const candidate = savedModel && catalog.some((m) => m.id === savedModel)
      ? savedModel
      : savedName && catalog.find((m) => m.name === savedName)?.id
        || (catalog.some((m) => m.id === selectedModel) ? selectedModel : catalog[0].id);

    if (candidate !== selectedModel) {
      onModelChange(candidate);
    }
    if (savedModel && savedModel !== candidate) {
      localStorage.removeItem('selectedModel');
    } else if (candidate !== savedModel) {
      localStorage.setItem('selectedModel', candidate);
    }
  }, [picker, visibleModels]);

  const handleModelSelect = (modelId: string) => {
    onModelChange(modelId);
    localStorage.setItem('selectedModel', modelId);
    setIsOpen(false);
  };

  const selectedModelData = visibleModels.find(model => model.id === selectedModel)
    || modelOptions.find(model => model.id === selectedModel)
    || visibleModels[0]
    || modelOptions[0];

  return (
    <TooltipProvider>
      <DropdownMenu open={isOpen} onOpenChange={setIsOpen}>
        <DropdownMenuTrigger asChild>
          <Button 
            variant="ghost" 
            className={`h-6 px-2 justify-between min-w-[120px] max-w-[180px] text-xs font-medium text-foreground hover:bg-muted/50 ${className}`}
            disabled={disabled}
          >
            <div className="flex items-center min-w-0 flex-1">
              {selectedModelData.hasReasoning && (
                <Brain className="w-1 h-1 mr-1" />
              )}
              <span className="truncate flex-1">{selectedModelData.displayName}</span>
            </div>
            <ChevronDown className="h-2.5 w-2.5 ml-1 flex-shrink-0" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-[280px] max-h-[300px] overflow-y-auto" align="end">
          <DropdownMenuLabel className="flex items-center gap-2 text-xs">
            <Brain className="w-4 h-4" />
            Choose Model
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          
          {visibleModels.map((model) => {
            const pricingInfo = modelPricing[model.id] || modelPricing[`google/${model.name}`];
            return (
              <Tooltip key={model.id}>
                <TooltipTrigger asChild>
                  <DropdownMenuItem
                    onClick={() => handleModelSelect(model.id)}
                    className="p-2 cursor-pointer focus:bg-muted/50 hover:bg-muted/70 transition-colors duration-200"
                  >
                    <div className="flex items-center justify-between w-full">
                      <div className="flex items-center min-w-0 flex-1">
                        {model.hasReasoning && (
                          <Brain className="w-1 h-1 flex-shrink-0 mr-1.5" />
                        )}
                        <div className="min-w-0 flex-1">
                        <span className="font-medium text-xs truncate">{model.displayName}</span>
                      </div>
                    </div>
                    <div className="flex flex-col items-end text-xs text-muted-foreground flex-shrink-0 ml-2">
                      <span className="font-mono">{model.contextLength}</span>
                    </div>
                  </div>
                  </DropdownMenuItem>
                </TooltipTrigger>
                {(pricingInfo || model.isSlow) && (
                  <TooltipContent 
                    className="bg-black text-yellow-400 border-gray-600 text-xs" 
                    side="left"
                    sideOffset={5}
                  >
                    {pricingInfo && <p className="font-medium">{pricingInfo}</p>}
                    {model.isSlow && <p className="font-medium text-orange-400">{pricingInfo ? '• ' : ''}Heavy slow reasoning</p>}
                  </TooltipContent>
                )}
              </Tooltip>
            );
          })}
          
          <DropdownMenuSeparator />
          <div className="p-1.5 text-xs text-muted-foreground text-center">
            AI Model Selection
          </div>
        </DropdownMenuContent>
      </DropdownMenu>
    </TooltipProvider>
  );
} 
